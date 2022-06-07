from pai.common import ProviderAlibabaPAI
from pai.operator import ContainerOperator
from pai.operator.types import (
    PipelineArtifact,
    LocationArtifactMetadata,
    LocationType,
    DataType,
    PipelineParameter,
    MetadataBuilder,
)
from pai.pipeline import Pipeline
from pai.pipeline.step import PipelineStep
from tests.unit import BaseUnitTestCase


class TestPipelineBuild(BaseUnitTestCase):

    RepeatedArtifactExampleIdentifier = "repeated_artifact_example"

    def test_repeated_artifact_case_1(self):

        input_table = PipelineArtifact(
            "input_table",
            metadata=LocationArtifactMetadata(
                data_type=DataType.DataSet, location_type=LocationType.MaxComputeTable
            ),
        )

        step1 = PipelineStep.from_registered_op(
            identifier="split",
            provider=ProviderAlibabaPAI,
            version="v1",
            inputs={"inputTable": input_table},
        )

        step2 = PipelineStep.from_registered_op(
            identifier=self.RepeatedArtifactExampleIdentifier,
            provider=ProviderAlibabaPAI,
            version="v1",
            inputs={
                "input1": [
                    step1.outputs.artifacts[0],
                    step1.outputs.artifacts[1],
                    "odps://pai_online_project/tables/wumai_data",
                ],
            },
        )

        step3 = PipelineStep.from_registered_op(
            identifier=self.RepeatedArtifactExampleIdentifier,
            provider=ProviderAlibabaPAI,
            version="v1",
            inputs={
                "input1": [
                    step2.outputs.artifacts[0][10],
                    step1.outputs.artifacts[1],
                    "odps://pai_online_project/tables/wumai_data",
                ],
            },
        )

        _ = Pipeline(steps=[step3], outputs=[step3.outputs[0], step1.outputs[0]])

    def test_io_name_conflict(self):
        input_params = [
            PipelineParameter(name="input1", default="hello"),
            PipelineParameter(name="input2", default="world"),
        ]
        output_artifacts = [
            PipelineArtifact(name="output1", metadata=MetadataBuilder.raw()),
            PipelineArtifact(name="output2", metadata=MetadataBuilder.raw()),
        ]

        op = ContainerOperator(
            image_uri="python:3",
            inputs=input_params,
            outputs=output_artifacts,
            command="echo hello",
        )
        step1 = op.as_step(name="step1")
        step2 = op.as_step(name="step2")

        _ = Pipeline(
            steps=[step1, step2],
            outputs={
                "step1_output1": step1.outputs["output1"],
                "step1_output2": step2.outputs["output1"],
            },
        )

        with self.assertRaisesRegexp(ValueError, ".*conflict.*") as _:
            step1 = op.as_step(name="step1")
            step2 = op.as_step(name="step2")
            _ = Pipeline(
                steps=[step1, step2],
                outputs=[step1.outputs["output1"], step2.outputs["output1"]],
            )

    def test_condition_step(self):

        inputs = [
            PipelineParameter(name="foo", default="hello"),
            PipelineParameter(name="bar", default="world"),
        ]
        outputs = [
            PipelineParameter(name="outputParam"),
        ]

        op = ContainerOperator(
            image_uri="python:3",
            inputs=inputs,
            outputs=outputs,
            command="echo hello",
        )

        step1 = op.as_step(
            name="step1",
        )

        eq_case = op.as_condition_step(
            condition=step1.outputs[0] == "true", name="step1", inputs={}
        ).to_dict()

        self.assertEqual(
            eq_case["spec"]["when"],
            "{{pipelines.step1.outputs.parameters.outputParam}} == true",
        )

        neq_case = op.as_condition_step(
            condition=step1.outputs[0] != "true", name="step1", inputs={}
        ).to_dict()

        self.assertEqual(
            neq_case["spec"]["when"],
            "{{pipelines.step1.outputs.parameters.outputParam}} != true",
        )

        lt_case = op.as_condition_step(
            condition=step1.outputs[0] < "true", name="step1", inputs={}
        ).to_dict()

        self.assertEqual(
            lt_case["spec"]["when"],
            "{{pipelines.step1.outputs.parameters.outputParam}} < true",
        )

        gt_case = op.as_condition_step(
            condition=step1.outputs[0] > "true", name="step1", inputs={}
        ).to_dict()

        self.assertEqual(
            gt_case["spec"]["when"],
            "{{pipelines.step1.outputs.parameters.outputParam}} > true",
        )
        geq_case = op.as_condition_step(
            condition=step1.outputs[0] >= "true", name="step1", inputs={}
        ).to_dict()
        self.assertEqual(
            geq_case["spec"]["when"],
            "{{pipelines.step1.outputs.parameters.outputParam}} >= true",
        )

        leq_case = op.as_condition_step(
            condition=step1.outputs[0] <= "true", name="step1", inputs={}
        ).to_dict()
        self.assertEqual(
            leq_case["spec"]["when"],
            "{{pipelines.step1.outputs.parameters.outputParam}} <= true",
        )

    def test_loop_step(self):
        inputs = [
            PipelineParameter(name="foo", default="hello"),
            PipelineParameter(name="bar", default="world"),
        ]
        outputs = [
            PipelineParameter(name="outputParam"),
        ]

        op = ContainerOperator(
            image_uri="python:3",
            inputs=inputs,
            outputs=outputs,
            command="echo hello",
        )

        range_case = op.as_loop_step(items=range(0, 10), name="step1").to_dict()

        self.assertEqual(
            range_case["spec"]["withSequence"],
            {
                "start": 0,
                "end": 10,
            },
        )

        item_list_case = op.as_loop_step(
            items=[
                {
                    "foo": "bar",
                },
                {
                    "hello": "world",
                },
            ],
            name="step1",
        ).to_dict()

        self.assertEqual(
            item_list_case["spec"]["withItems"],
            [
                {
                    "foo": "bar",
                },
                {
                    "hello": "world",
                },
            ],
        )

        output_step1 = op.as_step(name="stepOutput")
        output_param_case = op.as_loop_step(
            items=output_step1.outputs[0], name="step1"
        ).to_dict()

        self.assertEqual(
            output_param_case["spec"]["withParam"],
            "{{pipelines.stepOutput.outputs.parameters.outputParam}}",
        )
