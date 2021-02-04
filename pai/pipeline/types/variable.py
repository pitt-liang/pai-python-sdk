from __future__ import absolute_import

from abc import ABCMeta, abstractmethod

from six import with_metaclass


class PipelineVariable(with_metaclass(ABCMeta, object)):
    """Base class of Artifact and PipelineParameter."""

    variable_category = None

    def __init__(
        self,
        name,
        desc=None,
        io_type="inputs",
        value=None,
        from_=None,
        required=None,
        parent=None,
        validator=None,
    ):
        """

        Args:
            name: name of parameter.
            desc: parameter description.
            io_type: usage of PipelineParameter in pipeline, either "input" or "output"
            value: default value of parameter
            from_:
            required:
            validator: parameter value validator.
            parent:
        """
        self.name = name
        self.io_type = io_type
        self.desc = desc
        self.value = value
        self.from_ = from_
        self.required = required
        self.parent = parent
        self.validator = validator

    # TODO: validate if pipeline variable attribute is legal
    def _validate_spec(self):
        pass

    @abstractmethod
    def validate_value(self, val):
        pass

    @abstractmethod
    def validate_from(self, val):
        pass

    def assign(self, arg):
        from .artifact import PipelineArtifactElement

        if not isinstance(arg, (PipelineVariable, PipelineArtifactElement)):
            if not self.validate_value(arg):
                raise ValueError("Arg:%s is invalid value for %s" % (arg, self))
            self.value = arg
        else:
            if not self.validate_from(arg):
                raise ValueError(
                    "invalid assignment. %s left: %s, right: %s"
                    % (self.fullname, self.typ, arg.typ)
                )
            self.from_ = arg

    @property
    def fullname(self):
        """Unique identifier in pipeline manifest for PipelineVariable"""
        from pai.operator._base import OperatorBase

        if self.parent and not isinstance(self.parent, OperatorBase):
            return ".".join(
                [self.parent.ref_name, self.io_type, self.variable_category, self.name]
            )
        else:
            return ".".join([self.io_type, self.variable_category, self.name])

    def bind(self, parent, io_type):
        if self.parent and parent != self.parent:
            raise ValueError(
                "Pipeline variable has bound to another operator instance."
            )
        self.parent = parent
        self.io_type = io_type

    @property
    def enclosed_fullname(self):
        return "{{%s}}" % self.fullname

    def __str__(self):
        return self.__repr__()

    def __repr__(self):
        return "%s:{Name:%s, Kind:%s, Required:%s, Value:%s, Desc:%s}" % (
            type(self).__name__,
            self.name,
            self.io_type,
            self.required,
            self.value,
            self.desc,
        )

    def translate_argument(self, value):
        arguments = {
            "name": self.name,
            "value": value,
        }
        return arguments

    def to_argument(self):
        argument = {"name": self.name}
        if self.from_:
            argument["from"] = self.from_.enclosed_fullname
        else:
            argument["value"] = self.value
        return argument

    def depend_steps(self):
        from pai.pipeline import PipelineStep

        if self.from_ and self.from_.parent and isinstance(self.from_, PipelineStep):
            return self.from_

    def to_dict(self):
        d = {
            "name": self.name,
        }

        if self.validator:
            d["feasible"] = self.validator.to_dict()

        elif self.from_ is not None:
            if isinstance(self.from_, PipelineVariable):
                d["from"] = "{{%s}}" % self.from_.fullname
            else:
                d["from"] = self.from_

        return d
