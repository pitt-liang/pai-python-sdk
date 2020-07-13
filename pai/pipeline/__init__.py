from __future__ import absolute_import

import copy
import logging
from collections import OrderedDict, defaultdict
from collections import deque

import six
import yaml
from graphviz import Digraph

from pai.pipeline.artifact import create_artifact, ArtifactType
from pai.pipeline.parameter import create_pipeline_parameter, PipelineParameter
from pai.pipeline.variable import PipelineVariable
from pai.pipeline.run import RunInstance

DEFAULT_PIPELINE_API_VERSION = "core/v1"

logger = logging.getLogger(__name__)


class Pipeline(object):

    def __init__(self, session=None, metadata=None, pipeline_id=None,
                 inputs=None, outputs=None, api_version=DEFAULT_PIPELINE_API_VERSION):
        self.session = session
        self.metadata = metadata
        self.inputs = inputs or OrderedDict()
        self.outputs = outputs or OrderedDict()
        self.steps = OrderedDict()
        self.execution = None
        self.pipelines = []
        self.pipeline_id = pipeline_id
        self.api_version = api_version
        self._default_step_inputs = dict()

    @property
    def identifier(self):
        return self.metadata["identifier"]

    @property
    def version(self):
        return self.metadata["version"]

    @property
    def provider(self):
        return self.metadata["provider"]

    @classmethod
    def new_pipeline(cls, identifier, version, session):
        """
        Create new pipeline instance without inputs/outputs definition and implementation. Pipeline provider
         is assigned as account id of Alibaba Cloud from session.

        Args:
            identifier: identifier of new pipeline.
            version: pipeline version.
            session: session used for communicate with pai pipeline service.

        Returns:
            pipeline instance ready for define inputs, outputs and implementation.
        """
        provider = session.account_id
        pipeline = Pipeline(session=session, metadata={
            "identifier": identifier,
            "provider": provider,
            "version": version,
        })
        return pipeline

    def create_input_parameter(self, name, typ, desc=None, required=False, value=None):
        """

        Args:
            name: parameter name.
            typ: type of parameter, either string or primitive python (str, int, ...)
            desc:
            required:
            value:

        Returns:
            parameter instance define the pipeline input.

        Raises:
            ValueError if conflict in inputs dict.

        """
        if name in self.inputs:
            raise ValueError("Input variable name conflict: input %s exists" % name)
        param = create_pipeline_parameter(name=name, typ=typ, kind="inputs", desc=desc,
                                          required=required, value=value, parent=self)
        self.inputs[name] = param
        return param

    def create_input_artifact(self, name, data_type, location_type, model_type=None, desc=None, required=False,
                              value=None):
        typ = ArtifactType(data_type=data_type, location_type=location_type, model_type=model_type)
        af = create_artifact(name=name, typ=typ, kind="inputs", desc=desc,
                             required=required, value=value, parent=self)
        if name in self.inputs:
            raise ValueError("Input variable name conflict: input %s exists" % name)
        self.inputs[name] = af
        return af

    def create_output_parameter(self, name, from_, desc=None):
        typ = from_.typ
        param = create_pipeline_parameter(name=name, typ=typ, kind="outputs", desc=desc, parent=self, from_=from_)
        self.outputs[name] = param
        return param

    def create_output_artifact(self, name, from_, desc=None):
        typ = from_.typ
        af = create_artifact(name=name, typ=typ, kind="outputs", desc=desc, parent=self, from_=from_)
        self.outputs[name] = af
        return af

    def create_step(self, identifier, name, provider=None, version="v1"):
        """
        identifier + provider => uk

        latest version

        Args:
            identifier:
            provider:
            version:
            name:

        Returns:

        """

        provider = provider if provider else self.session.account_id
        pipeline_info = self.session.get_pipeline(identifier, provider, version)
        step = PipelineStep.create_from_manifest(pipeline_info["Manifest"], parent=self, name=name)
        return self._add_step(name, step)

    def create_step_from_manifest(self, manifest, name):
        step = PipelineStep.create_from_manifest(manifest, parent=self, name=name)
        return self._add_step(name, step)

    def _add_step(self, name, step):
        self.steps[name] = step
        default_inputs = {name: value for name, value in self._default_step_inputs.items() if name in step.inputs}
        step.set_arguments(**default_inputs)
        return step

    def to_estimator(self, parameters):
        from pai.estimator import PipelineEstimator
        manifest = self.to_dict()
        if self.pipeline_id:
            return PipelineEstimator.from_pipeline_id(pipeline_id=self.pipeline_id, session=self.session,
                                                      parameters=parameters)
        else:
            return PipelineEstimator.from_manifest(manifest, session=self.session, parameters=parameters)

    @classmethod
    def _load_by_manifest(cls, manifest, pipeline_id=None):
        """Create pipeline instance from pipeline definition manifest

        Args:
            manifest: pipeline manifest.
            pipeline_id:

        """
        if isinstance(manifest, six.string_types):
            manifest = yaml.load(manifest, yaml.FullLoader)
        api_version = manifest["apiVersion"]
        metadata = manifest["metadata"]
        spec = manifest["spec"]
        identifier, provider, version = metadata["identifier"], metadata["provider"], metadata["version"]
        p = Pipeline(pipeline_id=pipeline_id, metadata={
            "identifier": identifier,
            "provider": provider,
            "version": version,
        }, api_version=api_version)

        p = _load_input_output_spec(p, spec)
        if "pipelines" in spec and "execution" in spec:
            raise ValueError("Manifest schema error: Both spec.pipelines and spec.execution is defined")

        if "execution" in spec:
            p.execution = spec["execution"]
        elif "pipelines" in spec:
            p.pipelines = spec["pipelines"]

        return p

    def set_step_input(self, arg_name, arg_value):
        self._default_step_inputs[arg_name] = arg_value

    @classmethod
    def get_by_pipeline_id(cls, session, pipeline_id):
        pipeline_info = session.get_pipeline_by_id(pipeline_id)
        p = cls._load_by_manifest(pipeline_info["Manifest"], pipeline_id=pipeline_id)
        p.session = session
        return p

    @classmethod
    def get_by_identifier(cls, session, identifier, provider, version):
        pipeline_info = session.get_pipeline(identifier=identifier, provider=provider, version=version)
        p = cls._load_by_manifest(pipeline_info["Manifest"], pipeline_id=pipeline_info["PipelineId"])
        p.session = session
        return p

    @property
    def ref_name(self):
        return ""

    def cycle_detection(self):
        """Detect if cycle exists in pipeline graph.

        Returns:
            True if cycle detected.
        """
        dependencies = {step.name: set(step.dependencies.keys()) for step in self.steps.values()}
        count = len(dependencies)
        entries = {step.name for step in self.steps.values() if not step.dependencies}
        if not entries and dependencies:
            raise ValueError("Cycle detected in pipeline: independent entry not found")
        rev_dependencies = defaultdict(set)
        for step_name, parents in dependencies.items():
            for parent in parents:
                rev_dependencies[parent].add(step_name)

        untraveled_steps = {step_name: set(previous_steps) for step_name, previous_steps in dependencies.items() if
                            step_name not in entries}
        queue = deque(entries)
        while len(queue) > 0 and count > 0:
            count -= 1
            cur_item = queue.pop()
            downsides = rev_dependencies[cur_item]
            for step in downsides:
                untraveled_steps[step].remove(cur_item)
                if len(untraveled_steps[step]) == 0:
                    queue.append(step)
        untraveled = {step_name for step_name, previous_steps in untraveled_steps.items() if len(previous_steps) > 0}
        if len(untraveled):
            logger.error("Pipeline Cycle detected, untraveled steps: %s" % ','.join(untraveled))

        return len(untraveled) > 0

    def validate_step_name(self, name):
        if name in self.steps:
            raise ValueError("Pipeline step name conflict: %s" % name)
        return name

    # todo: input arguments validation.
    def run(self, name, arguments, env=None, wait=True):
        pipeline_id, manifest = None, None
        if self.pipeline_id:
            pipeline_id = self.pipeline_id
        else:
            manifest = self.to_dict()
        run_id = self.session.create_pipeline_run(name, arguments, env, no_confirm_required=True,
                                                  pipeline_id=pipeline_id, manifest=manifest)

        if not wait:
            return run_id
        run_instance = RunInstance(run_id=run_id, session=self.session)
        run_instance.wait()
        return run_id

    def _convert_spec_to_json(self):
        spec = {
            "inputs": dict(),
            "outputs": dict(),
        }

        inputs = [(arg.variable_category, arg.to_dict()) for arg in self.inputs.values()]
        for cat, v in inputs:
            if cat in spec["inputs"]:
                spec["inputs"][cat].append(v)
            else:
                spec["inputs"][cat] = [v]

        outputs = [(arg.variable_category, arg.to_dict()) for arg in self.outputs.values()]
        for cat, v in outputs:
            if cat in spec["outputs"]:
                spec["outputs"][cat].append(v)
            else:
                spec["outputs"][cat] = [v]

        if self.execution:
            spec["execution"] = self.execution
        else:
            spec["pipelines"] = [step.to_dict() for step in self.steps.values()]
        return {k: v for k, v in spec.items() if v}

    def dot(self):
        graph = Digraph()
        for step_name, step in self.steps.items():
            graph.node(step_name)
            for head in step.dependencies.keys():
                graph.edge(head, step_name)
        return graph

    def to_dict(self):
        manifest = {
            "apiVersion": self.api_version,
            "metadata": self.metadata,
            "spec": self._convert_spec_to_json()
        }
        return manifest


class PipelineStep(object):
    """
    PipelineStep instance is work node in pipeline.
    """

    def __init__(self, metadata, inputs=None, outputs=None, parent=None, dependencies=None):
        self.metadata = metadata
        self.inputs = inputs or OrderedDict()
        self.outputs = outputs or OrderedDict()
        self.parent = parent
        self.dependencies = dependencies or dict()

    @property
    def name(self):
        return self.metadata["name"]

    @classmethod
    def create_from_manifest(cls, manifest, parent, name=None):
        if isinstance(manifest, six.string_types):
            manifest = yaml.load(manifest, yaml.FullLoader)

        metadata = copy.copy(manifest["metadata"])
        metadata["name"] = parent.validate_step_name(name)
        step = PipelineStep(metadata=metadata, parent=parent)
        step = _load_input_output_spec(step, manifest["spec"])
        return step

    def set_arguments(self, **kwargs):
        """Config input parameter of pipeline step.

        step.set_arguments set the source of input parameters, from one of input of pipeline, output of upstream step,
        and default_parameter_input. It also inspect correctness of pipeline, by directed cycle detection,
        input requirement identification, parameter type check.

        Args:
            **kwargs:

        """
        dependencies = dict()
        for name, arg in kwargs.items():
            self.inputs[name].assign(arg)
            if isinstance(arg, PipelineVariable) and isinstance(arg.parent, PipelineStep):
                dependencies[arg.parent.name] = arg.parent

        for step in dependencies.values():
            self._add_dependency(step)

        if self.parent.cycle_detection():
            raise ValueError("Cycle detected in pipeline")

        # for step_input in self.inputs.values():
        #     if step_input.required and not step_input.is_assigned and step_input.value is None:
        #         raise ValueError("Parameter: %s is required but not assigned" % step_input.fullname)

    def _add_dependency(self, step):
        if not step:
            return
        if not isinstance(step, PipelineStep):
            raise ValueError("Dependent task should by instance of PipelineStep")
        if self.parent != step.parent:
            raise ValueError("Dependent task should belong to the same parent pipeline")
        self.dependencies[step.name] = step

    def after(self, *steps):
        dependencies = {step.name: step for step in steps}
        for step in dependencies.values():
            self._add_dependency(step)
        if self.parent.cycle_detection:
            raise ValueError("Cycle detected in pipeline.")

    @property
    def ref_name(self):
        return "pipelines.{}".format(self.name)

    def _convert_spec_to_json(self):
        spec = {
            "arguments": dict(),
        }
        inputs = [(arg.variable_category, arg.to_argument()) for arg in self.inputs.values() if arg.is_assigned]
        for cat, v in inputs:
            if cat in spec["arguments"]:
                spec["arguments"][cat].append(v)
            else:
                spec["arguments"][cat] = [v]

        if self.dependencies:
            spec["dependencies"] = list(self.dependencies.keys())
        return spec

    def to_dict(self):
        d = {
            "metadata": self.metadata,
            "spec": self._convert_spec_to_json(),
        }
        return d


def _load_input_output_spec(p, spec):
    for param in spec["inputs"].get("parameters", []):
        _load_parameter(p, param, "inputs")

    for af in spec["inputs"].get("artifacts", []):
        _load_artifact(p, af, "inputs")

    for param in spec["outputs"].get("parameters", []):
        _load_parameter(p, param, "outputs")

    for af in spec["outputs"].get("artifacts", []):
        _load_artifact(p, af, "outputs")
    return p


def _load_parameter(p, param_spec, kind):
    assert kind in ("inputs", "outputs")

    typ = param_spec.pop("type", None)
    name = param_spec.pop("name")
    from_ = param_spec.pop("from", None)
    feasible = param_spec.pop("feasible", None)
    value = param_spec.pop("value", None)
    desc = param_spec.pop("desc", None)
    required = param_spec.pop("required", False)

    param = create_pipeline_parameter(name=name, typ=typ, kind=kind, parent=p, from_=from_,
                                      feasible=feasible, value=value, desc=desc, required=required)
    getattr(p, kind)[name] = param
    return param


def _load_artifact(p, artifact_spec, kind):
    assert kind in ("inputs", "outputs")
    typ = ArtifactType.from_dict(artifact_spec.pop("type", None))
    name = artifact_spec.pop("name", None)
    from_ = artifact_spec.pop("from", None)
    value = artifact_spec.pop("value", None)
    desc = artifact_spec.pop("desc", None)
    required = artifact_spec.pop("required", False)

    af = create_artifact(name=name, typ=typ, kind=kind, parent=p, from_=from_,
                         value=value, desc=desc, required=required)
    getattr(p, kind)[name] = af
    return af


def default_step_parameter(typ, value):
    return create_pipeline_parameter(name=None, typ=typ, kind="outputs", value=value)
