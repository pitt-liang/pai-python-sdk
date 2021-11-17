# coding: utf-8
import time

from pai.operator import ContainerOperator, SavedOperator
from pai.operator.types import (
    PipelineArtifact,
    LocationArtifactMetadata,
    DataType,
    LocationType,
)
from pai.operator.types import (
    PipelineParameter,
)
from pai.pipeline import Pipeline
from tests.integration import BaseIntegTestCase


class TestContainerOperator(BaseIntegTestCase):
    def test_component_base(self):
        inputs = [
            PipelineParameter(name="xflow_name", typ=str, desc="ExampleParam"),
            PipelineArtifact(
                name="inputs1",
                metadata=LocationArtifactMetadata(
                    data_type=DataType.DataSet, location_type=LocationType.OSS
                ),
                desc="ExampleInputArtifact",
            ),
        ]
        outputs = [
            PipelineArtifact(
                name="output1",
                metadata=LocationArtifactMetadata(
                    data_type=DataType.DataSet, location_type=LocationType.OSS
                ),
                desc="ExampleOutputArtifact",
            ),
        ]

        container_templ = ContainerOperator(
            image_uri=self.get_python_image(),
            inputs=inputs,
            outputs=outputs,
            command=[
                "python",
                "-c",
                "import os; print('\\n'.join(['%s=%s' % (k, v) for k, v in os.environ.items()]));",
            ],
            env={"HelloWorld": '"{{inputs.parameters}}"'},
        )

        version = "v-%s" % int(time.time())
        registered_op = container_templ.save(identifier="ExampleOp", version=version)
        self.assertEqual(registered_op.inputs["xflow_name"].desc, "ExampleParam")
        self.assertEqual(registered_op.inputs["inputs1"].desc, "ExampleInputArtifact")
        self.assertEqual(registered_op.outputs["output1"].desc, "ExampleOutputArtifact")
        container_templ.run(
            job_name="hello-world",
            arguments={
                "xflow_name": "abcd",
            },
        )
        registered_op.delete()

    def test_container_op_crud(self):
        op1 = ContainerOperator(
            image_uri=self.get_python_image(),
            inputs=[],
            outputs=[],
            command=[
                "python",
                "-c",
                "import os; print('\\n'.join(['%s=%s' % (k, v) for k, v in os.environ.items()]));",
            ],
        )

        op_version = "v-%s" % int(time.time())
        op_identifier = "containerOpExample"

        # test register and get component
        reg_op = op1.save(identifier=op_identifier, version=op_version)
        remote_op = SavedOperator.get_by_identifier(
            identifier=op_identifier, version=op_version
        )

        assert reg_op == remote_op

        # test update component manifest
        op2 = ContainerOperator(
            image_uri=self.get_python_image(),
            inputs=[],
            outputs=[],
            command=[
                "echo",
                "HelloWorld",
            ],
        )
        op2_manifest = op2.to_manifest(identifier=op_identifier, version=op_version)
        reg_op.update(op2_manifest)

        # test delete component
        reg_op.delete()
        with self.assertRaises(ValueError):
            _ = SavedOperator.get_by_identifier(
                identifier=op_identifier, version=op_version
            )

    def test_pipeline_update(self):

        op1 = ContainerOperator(
            image_uri=self.get_python_image(),
            inputs=[PipelineParameter("x", default="10")],
            outputs=[],
            command=[
                "python",
                "-c",
                "import os; print('\\n'.join(['%s=%s' % (k, v) for k, v in os.environ.items()]));",
            ],
        )

        def create_pipeline(x):
            step1 = op1.as_step("step1", inputs={"x": x})
            step2 = op1.as_step("step2", inputs={"x": x})
            return Pipeline(steps=[step1, step2])

        p = create_pipeline(10)

        version = "v-%s" % int(time.time())
        identifier = "examplePipeline"

        reg_pipeline = p.save(identifier=identifier, version=version)

        p2 = create_pipeline(100)

        p2_manifest = p2.to_manifest(identifier=identifier, version=version)
        reg_pipeline.update(op=p2_manifest)
        reg_pipeline.delete()
