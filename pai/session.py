from __future__ import absolute_import

import six
import yaml
from aliyunsdkcore.client import AcsClient
from odps import ODPS

from pai.api.client_factory import ClientFactory
from pai.utils import run_detail_url


class Session(object):

    def __init__(self, access_key_id, access_key_secret, region_id,
                 odps_project=None, odps_endpoint=None):
        """ Wrap all functionality provided by Alibaba Cloud PAI services

        This class encapsulates convenient methods to access PAI services, currently focus
        on Pipeline service, future include EAS inference service, Model optimize, etc.

        Args:
            access_key_id (str): Alibaba Cloud access key id.
            access_key_secret (str): Alibaba Cloud access key secret.
            region_id (str): Alibaba Cloud region id
        """

        if not access_key_id or not access_key_secret or not region_id:
            raise ValueError("Please provide access_key, access_secret and region")

        self.region_id = region_id

        self._initialize(access_key_id, access_key_secret, region_id,
                         odps_project=odps_project, odps_endpoint=odps_endpoint)

    def _initialize(self, access_key, access_secret, region, odps_project=None,
                    odps_endpoint=None):

        # paiflow_acs_client = AcsClient(
        #     ak="AccessKeyId",
        #     secret="zXJ7QF79Oz",
        #     region_id="ch-shanghai",
        # )

        self._acs_client = AcsClient(ak=access_key, secret=access_secret, region_id=region)
        self.paiflow_client = ClientFactory.create_paiflow_client(self._acs_client)

        self.sts_client = ClientFactory.create_sts_client(self._acs_client)
        self.odps_client = ODPS(access_id=access_key, secret_access_key=access_secret,
                                project=odps_project,
                                endpoint=odps_endpoint)
        self._init_account()

    @property
    def account_id(self):
        return self._account_id

    @property
    def user_id(self):
        return self._user_id

    @property
    def rolearn(self):
        return self._arn

    def _init_account(self):
        caller_identity = self.sts_client.get_caller_identity()
        print(caller_identity)
        self._account_id = int(caller_identity["AccountId"])
        self._user_id = int(caller_identity["UserId"])
        self._arn = caller_identity["Arn"]

    @property
    def odps_project(self):
        return self.odps_client.project

    def get_pipeline(self, identifier, provider, version):
        pipeline_info = self.paiflow_client.get_pipeline(identifier=identifier,
                                                         provider=provider,
                                                         version=version)["Data"]
        # TODO: remove `provider` injection after backend completed
        # manifest = yaml.load(pipeline_info["Manifest"])
        # manifest["metadata"]["provider"] = provider
        # pipeline_info["Manifest"] = yaml.dump(manifest)
        return pipeline_info

    def get_pipeline_by_id(self, pipeline_id):
        return self.paiflow_client.get_pipeline(pipeline_id=pipeline_id)["Data"]

    def search_pipeline(self, identifier=None, provider=None, fuzzy=None, version=None,
                        page_num=1, page_size=50):
        """List Pipelines

        Args:
            identifier: identifier of pipeline.
            provider: Alibaba Cloud account id of pipeline provider.
            fuzzy: if use fuzzy match
            source_type:
            version:
            page_num:
            page_size:

        Returns:

        """
        resp = self.paiflow_client.list_pipeline(
            identifier=identifier,
            provider=provider,
            fuzzy=fuzzy,
            version=version,
            page_num=page_num,
            page_size=page_size,
        )
        total_count = resp["TotalCount"]
        pipeline_infos = resp["Data"]
        return pipeline_infos, total_count

    def create_pipeline(self, pipeline_def):
        """
        create_pipeline submit `pipeline_manifest` to pipeline service and store.
        Identifier-provider-version is unique key. The same triple combination will
        result overwrite.

        Args:
            pipeline_def: pipeline definition manifest, support types Pipeline,

        Returns:
            pipeline_id
        """
        from pai.pipeline import Pipeline

        if isinstance(pipeline_def, dict):
            manifest = yaml.dump(pipeline_def)
        elif isinstance(pipeline_def, Pipeline):
            manifest = yaml.dump(pipeline_def.to_dict())
        elif not isinstance(pipeline_def, six.string_types):
            raise ValueError(
                "Not support argument `pipeline_def` type %s, expected dict, Pipeline or str.")
        resp = self.paiflow_client.create_pipeline(manifest=manifest)
        return resp["Data"]["PipelineId"]

    def describe_pipeline(self, pipeline_id):
        return self.paiflow_client.describe_pipeline(pipeline_id)

    def update_pipeline_privilege(self, pipeline_id, user_ids):
        return self.paiflow_client.update_pipeline_privilege(pipeline_id, user_ids)["Data"]

    def list_pipeline_privilege(self, pipeline_id):
        return self.paiflow_client.list_pipeline_privilege(pipeline_id)["Data"]

    def create_pipeline_run(self, name, arguments, env=None, pipeline_id=None, manifest=None,
                            no_confirm_required=True):
        arguments = {
            "arguments": arguments,
            "env": env
        }

        resp = self.paiflow_client.create_run(name, arguments, pipeline_id=pipeline_id,
                                              manifest=manifest,
                                              no_confirm_required=no_confirm_required)

        run_id = resp["Data"]["RunId"]

        print("Create pipeline run success (run_id: {run_id}), please visit the link below to view"
              " the run detail.".format(run_id=run_id))
        print(run_detail_url(run_id, self.region_id))

        return run_id

    def list_pipeline_run(self, name=None, run_id=None, pipeline_id=None, status=None,
                          sorted_by=None, sorted_sequences=None, page_num=1, page_size=50):
        kwargs = locals()
        kwargs.pop("self")
        run_infos = self.paiflow_client.list_run(**kwargs)
        return run_infos

    def get_run_detail(self, run_id, node_id, depth=2):
        run_info = self.paiflow_client.get_run_detail(run_id, node_id, depth=depth)
        return run_info["Data"]

    def get_run_log(self, run_id, node_id, from_time=None, to_time=None,
                    keyword=None, reverse=False, page_offset=0, page_size=100):
        kwargs = locals()
        kwargs.pop("self")
        logs = self.paiflow_client.list_node_log(**kwargs)
        return logs["Data"]

    def list_run_outputs(self, run_id, node_id, depth=1, name=None, sorted_by=None,
                         sorted_sequence=None, typ=None, page_number=1, page_size=50):
        outputs = self.paiflow_client.list_run_outputs(
            run_id=run_id,
            node_id=node_id,
            depth=depth,
            name=name,
            sorted_by=sorted_by,
            sorted_sequence=sorted_sequence,
            typ=typ,
            page_number=page_number,
            page_size=page_size,
        )["Data"]
        return outputs

    def get_run(self, run_id):
        run_info = self.paiflow_client.get_run(run_id)
        return run_info["Data"]

    def terminate_run(self, run_id):
        resp = self.paiflow_client.terminate_run(run_id)
        return resp["Data"]["runId"] == run_id

    def suspend_run(self, run_id):
        resp = self.paiflow_client.suspend_run(run_id)
        return resp["Data"]

    def retry_run(self, run_id):
        resp = self.paiflow_client.retry_run(run_id)
        return resp["Data"]["runId"] == run_id

    def resume_run(self, run_id):
        resp = self.paiflow_client.resume_run(run_id)
        return resp["Data"]

    def start_run(self, run_id):
        resp = self.paiflow_client.start_run(run_id)
        return resp["Data"]
