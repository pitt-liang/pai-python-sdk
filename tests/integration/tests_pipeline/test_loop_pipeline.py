import contextlib
import io
import json

from pai.operator import ContainerOperator
from pai.operator.types import PipelineParameter
from pai.operator.types.parameter import LoopItemPlaceholder
from pai.pipeline import Pipeline

from tests.integration import BaseIntegTestCase


class TestLoopPipeline(BaseIntegTestCase):
    def test_loop_with_sequence(self):
        op = ContainerOperator(
            inputs=[
                PipelineParameter("foo", default="valueFoo"),
                PipelineParameter("bar", default="valueBar"),
            ],
            image_uri="python:3",
            env={
                "PYTHONUNBUFFERED": "1",
            },
            command=[
                "bash",
                "-c",
                "echo foo={{inputs.parameters.foo}} bar=={{inputs.parameters.bar}}",
            ],
        )
        step1 = op.as_loop_step(
            name="loop-range",
            items=range(0, 10),
            parallelism=10,
            inputs={
                "foo": LoopItemPlaceholder(),
            },
        )
        p = Pipeline(steps=[step1])
        print(p.to_manifest(identifier="example", version="v1"))
        run_output = io.StringIO()
        with contextlib.redirect_stdout(run_output):
            p.run(job_name="test_loop_with_sequence")
        print(run_output)
        self.assertTrue(f"foo=1" in run_output.getvalue())

    def test_loop_with_param(self):
        output_param_name = "outputparam"
        output_params = json.dumps(["hello", "world"])
        op = ContainerOperator(
            inputs=[
                PipelineParameter("foo", default="valueFoo"),
                PipelineParameter("bar", default="valueBar"),
            ],
            outputs=[
                PipelineParameter(output_param_name),
            ],
            image_uri="python:3",
            env={
                "PYTHONUNBUFFERED": "1",
            },
            command=[
                "bash",
                "-c",
                "echo foo={{inputs.parameters.foo}} bar=={{inputs.parameters.bar}}"
                " && mkdir -p  /pai/outputs/parameters/ "
                " && echo '%s' > /pai/outputs/parameters/%s"
                " && cat  /pai/outputs/parameters/%s"
                % (output_params, output_param_name, output_param_name),
            ],
        )

        step1 = op.as_step(name="step1")
        step_loop = op.as_loop_step(
            name="loop-with-param",
            items=step1.outputs[0],
            inputs={"foo": "{{item}}"},
            parallelism=5,
        )
        step_valid = op.as_step(
            name="step-print-param",
            inputs={
                "foo": step1.outputs[0],
            },
        )
        p = Pipeline(steps=[step1, step_loop, step_valid])
        print(p.to_manifest(identifier="example", version="v1"))

        run_output = io.StringIO()
        with contextlib.redirect_stdout(run_output):
            p.run(job_name="test_loop_with_param")
        print(run_output.getvalue())
        self.assertTrue(f"foo=hello" in run_output.getvalue())
        self.assertTrue(f"foo=world" in run_output.getvalue())

    def test_loop_with_items(self):
        op = ContainerOperator(
            inputs=[
                PipelineParameter("foo", default="valueFoo"),
                PipelineParameter("bar", default="valueBar"),
            ],
            image_uri="python:3",
            env={
                "PYTHONUNBUFFERED": "1",
            },
            command=[
                "bash",
                "-c",
                "echo foo={{inputs.parameters.foo}} bar=={{inputs.parameters.bar}}",
            ],
        )

        step1 = op.as_loop_step(
            name="loop-with-items",
            items=["hello", "world"],
            inputs={"foo": LoopItemPlaceholder()},
        )
        p = Pipeline(steps=[step1])
        print(p.to_manifest(identifier="example", version="v1"))
        run_output = io.StringIO()
        with contextlib.redirect_stdout(run_output):
            run = p.run(job_name="test_loop_with_items")
        print(run_output.getvalue())
        self.assertTrue(f"foo=hello" in run_output.getvalue())
