from __future__ import absolute_import

import itertools

import six

from pai.operator.types.parameter import ConditionExpr, LoopItems, PipelineParameter
from pai.operator.types.spec import load_input_output_spec
from pai.operator.types.variable import PipelineVariable


class _OpRef(object):
    def __init__(self):
        pass

    def to_dict(self):
        pass


class RegisteredOperatorRef(_OpRef):
    def __init__(self, identifier, provider, version):
        super(RegisteredOperatorRef, self).__init__()
        self.identifier = identifier
        self.provider = provider
        self.version = version

    def to_dict(self):
        return {
            "identifier": self.identifier,
            "provider": self.provider,
            "version": self.version,
        }


class UnRegisteredOperatorRef(_OpRef):
    def __init__(self, guid):
        super(UnRegisteredOperatorRef, self).__init__()
        self.guid = guid

    def to_dict(self):
        return {"guid": self.guid}


class PipelineStep(object):
    """Represents an execution step in PAI pipeline.

    Pipeline steps can be configured together to construct a Pipeline, which is present as workflow
    in PAI ML pipeline service.

    """

    def __init__(
        self,
        inputs=None,
        name=None,
        depends=None,
        operator=None,
    ):
        """Construct a step which represent operator execution in pipeline.

        Args:
            inputs (dict): Inputs for the step in dict: key is the operator input name, value
                could be the output artifact/parameter from other step, input of the pipeline,
                or actual value for the step.
            name (str): Name of the step in pipeline, must be unique in the pipeline.
            depends (list): A list of PipelineStep which step depends.
            operator (OperatorBase): The operator used by the constructed step.
        """
        from ..operator import SavedOperator

        self._depends = depends or set()
        if any([type(x) for x in self._depends if not isinstance(x, PipelineStep)]):
            raise ValueError("Invalid variable in depends, expected PipelineStep")

        self._assigned = set()

        if isinstance(operator, SavedOperator):
            self.op_ref = RegisteredOperatorRef(
                identifier=operator.identifier,
                version=operator.version,
                provider=operator.provider,
            )
        else:
            self.op_ref = UnRegisteredOperatorRef(guid=operator.guid)

        self._name = name
        self._operator = operator

        (
            inputs_spec,
            outputs_spec,
        ) = load_input_output_spec(self, operator.io_spec_to_dict())
        self.parent = None
        self.inputs = inputs_spec
        self.outputs = outputs_spec

        self.assign_inputs(inputs)
        self._repeated_artifact_config = {}

    @property
    def is_op_registered(self):
        if isinstance(self.op_ref, RegisteredOperatorRef):
            return True
        return False

    @property
    def operator(self):
        return self._operator

    def gen_name_prefix(self):
        if self.is_op_registered:
            return self.op_ref.identifier
        return self.operator.name

    @classmethod
    def from_registered_op(
        cls,
        identifier,
        provider=None,
        version="v1",
        inputs=None,
        name=None,
        depends=None,
    ):
        """Build the PipelineStep from the given registered operator reference: identifier, version, provider.

        Args:
            identifier: Identifier of the registered operator.
            provider: Provider of the registered operator.
            version: Version of the registered operator.
            inputs: Inputs for the building step.
            name: Name for the building step.
            depends: Depended steps of the building step.

        Returns:
            PipelineStep: The built step instantiates from the given registered operator and inputs.
        """
        from ..operator import SavedOperator
        from ..core.session import Session

        provider = provider or Session.current().provider
        op = SavedOperator.get_by_identifier(
            identifier=identifier, provider=provider, version=version
        )

        if not op:
            raise ValueError(
                "Specific register operator not found: identifier={0}, provider={1}, version={2}".format(
                    identifier, provider, version
                )
            )
        return cls(
            inputs=inputs or [],
            name=name,
            depends=depends,
            operator=op,
        )

    @property
    def repeated_io_config(self):
        return self._repeated_artifact_config

    def set_artifact_count(self, artifact_name, count):
        artifacts = {
            item.name: item
            for item in itertools.chain(self.outputs.artifacts, self.inputs.artifacts)
        }
        artifact = artifacts.get(artifact_name)
        if not artifact:
            raise ValueError("artifact is not exists: %s" % artifact_name)

        if not artifact.repeated:
            raise ValueError("artifact is not repeated: %s", artifact_name)
        artifact.count = count
        return self

    # TODO: Confirm pipeline step name restriction
    @classmethod
    def _validate_name(cls, name):
        if name is None:
            return
        if not isinstance(name, six.string_types):
            raise ValueError("PipelineStep name should be string type")
        if not name:
            raise ValueError("PipelineStep name should not be empty str")
        if len(name) > 30:
            raise ValueError("Given invalid pipeline step name.")

    def assign_inputs(self, inputs):
        if not inputs:
            return
        assign_items = self.inputs.assign(inputs)
        self._assigned = self._assigned.union(set(item.name for item in assign_items))

        if isinstance(inputs, dict):
            inputs = inputs.values()

        values = []
        for ipt in inputs:
            if isinstance(ipt, (list, tuple)):
                values.extend(ipt)
            else:
                values.append(ipt)

        def _depend_step(input):
            from pai.operator.types.artifact import PipelineArtifactElement

            if isinstance(input, PipelineVariable) and input.parent:
                return input.parent
            elif isinstance(input, PipelineArtifactElement) and input.artifact.parent:
                return input.artifact.parent

        input_steps = set(filter(None, [_depend_step(val) for val in values]))

        self._depends = input_steps.union(self._depends)

    @property
    def depends(self):
        return list(self._depends)

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, value):
        self._name = value

    @classmethod
    def get_operator(cls, identifier, provider, version):
        from ..operator import SavedOperator

        operator = SavedOperator.get_by_identifier(
            identifier=identifier, provider=provider, version=version
        )
        return operator

    def after(self, *steps):
        if self.parent or any(step for step in steps if step.parent):
            raise ValueError(
                "Not allow operation, pipeline step has been included in a pipeline"
            )
        for step in steps:
            if step not in self._depends:
                self._depends.add(step)

    @property
    def ref_name(self):
        return "pipelines.{}".format(self.name)

    def _convert_spec_to_json(self):
        assigned_inputs = [ipt for ipt in self.inputs if ipt.name in self._assigned]

        repeated_artifact_config = [
            {
                "name": opt.name,
                "value": [None] * opt.count,
            }
            for opt in self.outputs.artifacts
            if opt.repeated and opt.count
        ]

        spec = {
            "arguments": {
                "parameters": [
                    ipt.to_argument()
                    for ipt in assigned_inputs
                    if ipt.variable_category == "parameters"
                ],
                "artifacts": [
                    ipt.to_argument()
                    for ipt in assigned_inputs
                    if ipt.variable_category == "artifacts"
                ]
                + repeated_artifact_config,
            }
        }

        if self._depends:
            spec["dependencies"] = [step.name for step in self.depends]
        return spec

    def to_dict(self):
        metadata = {"name": self.name}
        metadata.update(self.op_ref.to_dict())

        d = {
            "metadata": metadata,
            "spec": self._convert_spec_to_json(),
        }
        return d


class ConditionStep(PipelineStep):
    """Represent a conditional execution step in pipeline."""

    def __init__(self, condition, inputs=None, name=None, depends=None, operator=None):
        """Construct a ConditionStep to support conditional execution in pipeline.

        A ConditionStep only execute if condition evaluate to true.

        Args:
            condition (Union[str, ConditionExpr]): Condition expression used to determine
                if the step should be executed, could be ConditionExpr or str.
            inputs (dict): Inputs for the step in dict: key is the operator input name, value
                could be the output artifact/parameter from other step, input of the pipeline,
                or actual value for the step.
            name (str): Name of the step in pipeline, must be unique in the pipeline.
            depends (list): A list of PipelineStep which step depends.
            operator (OperatorBase): The operator used by the constructed step.
        """
        if not isinstance(condition, (ConditionExpr, str)):
            raise ValueError("Not supported condition type: %s" % type(condition))
        elif isinstance(condition, ConditionExpr):
            condition_depends = condition.get_depends_steps()
            depends = list(filter(None, (depends or []) + condition_depends))

        super().__init__(inputs=inputs, name=name, depends=depends, operator=operator)
        self.condition = condition

    def to_dict(self):
        d = super(ConditionStep, self).to_dict()
        d["spec"]["when"] = (
            self.condition.to_expr()
            if isinstance(self.condition, ConditionExpr)
            else str(self.condition)
        )
        return d


class LoopStep(PipelineStep):
    """Represent a parallel execution step in pipeline."""

    DEFAULT_PARALLELISM_COUNT = 5

    def __init__(
        self,
        items,
        parallelism=None,
        inputs=None,
        name=None,
        depends=None,
        operator=None,
    ):
        """Construct a LoopStep to support for-loop execution in pipeline.

        A LoopStep invoke the operator in for-loop execution style.

        Args:
            items (Union[str, ConditionExpr]): Condition expression used to determine
                if the step should be executed, could be ConditionExpr or str.
            parallelism (int): Max execution parallelism of the step.
            inputs (dict): Inputs for the step in dict: key is the operator input name, value
                could be the output artifact/parameter from other step, input of the pipeline,
                or actual value for the step.
            name (str): Name of the step in pipeline, must be unique in the pipeline.
            depends (list): A list of PipelineStep which step depends.
            operator (OperatorBase): The operator used by the constructed step.
        """
        if (
            isinstance(items, PipelineParameter)
            and items.parent
            and isinstance(items.parent, PipelineStep)
        ):
            depends = depends or []
            depends.append(items.parent)

        super().__init__(inputs=inputs, name=name, depends=depends, operator=operator)
        self.items = LoopItems(items)
        self.parallelism = int(parallelism or type(self).DEFAULT_PARALLELISM_COUNT)

    def to_dict(self):
        d = super(LoopStep, self).to_dict()
        d["spec"].update(self.items.to_dict())
        if self.parallelism:
            d["spec"]["parallelism"] = self.parallelism

        return d
