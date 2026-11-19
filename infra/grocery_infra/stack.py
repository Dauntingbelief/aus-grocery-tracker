"""All AWS resources for the grocery tracker, in one CloudFormation stack.

S3 bucket
├── reference/basket.csv          <- deployed from data/basket.csv by CDK
├── raw/prices/date=.../*.csv      <- you upload weekly CSVs here
│        │ (S3 event)
│        ▼
│   Lambda: transform              <- src/grocery_tracker + AWS SDK for pandas layer
│        │
├── processed/prices/year_month=.../part-0.parquet
│        ▲
│   Glue table grocery_tracker.prices (partition projection, no crawler)
│        ▲
│   Athena workgroup (query results -> athena-results/, auto-deleted after 7 days)
└── athena-results/

+ AWS Budgets: monthly $5 cost alert by email
"""

from __future__ import annotations

from pathlib import Path

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_athena as athena
from aws_cdk import aws_budgets as budgets
from aws_cdk import aws_glue as glue
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_deployment as s3deploy
from aws_cdk import aws_s3_notifications as s3n
from constructs import Construct

from grocery_tracker.schema import PARTITION_KEY, glue_columns

REPO_ROOT = Path(__file__).resolve().parents[2]

RAW_PREFIX = "raw/prices/"
PROCESSED_PREFIX = "processed/prices/"
BASKET_KEY = "reference/basket.csv"
ATHENA_PREFIX = "athena-results/"

# AWS-published layer bundling pandas + pyarrow (account 336392948345 is AWS's).
# Check the latest version: https://aws-sdk-pandas.readthedocs.io/en/stable/layers.html
PANDAS_LAYER_ACCOUNT = "336392948345"


class GroceryTrackerStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        budget_email: str,
        budget_limit_usd: float = 5.0,
        pandas_layer_version: int = 32,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ---------- S3: one private bucket, organised by prefix ----------
        bucket = s3.Bucket(
            self,
            "DataBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            # Raw CSVs are also in git, so it's safe to delete the bucket on `cdk destroy`.
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="expire-athena-results",
                    prefix=ATHENA_PREFIX,
                    expiration=Duration.days(7),
                )
            ],
        )

        s3deploy.BucketDeployment(
            self,
            "DeployBasket",
            sources=[
                s3deploy.Source.data("basket.csv", (REPO_ROOT / "data" / "basket.csv").read_text())
            ],
            destination_bucket=bucket,
            destination_key_prefix="reference/",
        )

        # ---------- Lambda: transform raw CSV -> Parquet ----------
        pandas_layer = lambda_.LayerVersion.from_layer_version_arn(
            self,
            "AwsSdkPandasLayer",
            f"arn:aws:lambda:{self.region}:{PANDAS_LAYER_ACCOUNT}:layer:"
            f"AWSSDKPandas-Python312:{pandas_layer_version}",
        )

        transform_logs = logs.LogGroup(
            self,
            "TransformLogs",
            retention=logs.RetentionDays.TWO_WEEKS,
            removal_policy=RemovalPolicy.DESTROY,
        )

        transform_fn = lambda_.Function(
            self,
            "TransformFunction",
            description="Rebuild processed Parquet from raw price CSVs",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.X86_64,
            handler="grocery_tracker.aws.transform_handler.handler",
            code=lambda_.Code.from_asset(
                str(REPO_ROOT / "src"),
                exclude=["**/__pycache__", "*.egg-info", "**/*.pyc"],
            ),
            layers=[pandas_layer],
            memory_size=1024,  # pandas import is CPU-bound; more memory = more CPU
            timeout=Duration.minutes(2),
            retry_attempts=0,  # bad data won't fix itself on retry; check the logs instead
            log_group=transform_logs,
            environment={
                "DATA_BUCKET": bucket.bucket_name,
                "RAW_PREFIX": RAW_PREFIX,
                "PROCESSED_PREFIX": PROCESSED_PREFIX,
                "BASKET_KEY": BASKET_KEY,
            },
        )
        # Least privilege: read raw + reference, write processed only. (grant_read also adds
        # s3:List* on the bucket, which IAM can't scope to a key prefix this way.)
        bucket.grant_read(transform_fn, f"{RAW_PREFIX}*")
        bucket.grant_read(transform_fn, BASKET_KEY)
        bucket.grant_put(transform_fn, f"{PROCESSED_PREFIX}*")

        bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.LambdaDestination(transform_fn),
            s3.NotificationKeyFilter(prefix=RAW_PREFIX, suffix=".csv"),
        )

        # ---------- Glue Data Catalog: table definition for Athena ----------
        database = glue.CfnDatabase(
            self,
            "GlueDatabase",
            catalog_id=self.account,
            database_input=glue.CfnDatabase.DatabaseInputProperty(
                name="grocery_tracker",
                description="Australian grocery basket prices and ABS CPI",
            ),
        )

        processed_location = f"s3://{bucket.bucket_name}/{PROCESSED_PREFIX}"
        prices_table = glue.CfnTable(
            self,
            "PricesTable",
            catalog_id=self.account,
            database_name="grocery_tracker",
            table_input=glue.CfnTable.TableInputProperty(
                name="prices",
                description="One row per product per store per collection date",
                table_type="EXTERNAL_TABLE",
                partition_keys=[{"name": PARTITION_KEY, "type": "string"}],
                parameters={
                    "classification": "parquet",
                    # Partition projection: Athena works out partitions from this rule
                    # instead of needing a crawler or MSCK REPAIR after each upload.
                    "projection.enabled": "true",
                    f"projection.{PARTITION_KEY}.type": "date",
                    f"projection.{PARTITION_KEY}.format": "yyyy-MM",
                    f"projection.{PARTITION_KEY}.range": "2026-01,NOW",
                    f"projection.{PARTITION_KEY}.interval": "1",
                    f"projection.{PARTITION_KEY}.interval.unit": "MONTHS",
                    "storage.location.template": (
                        f"{processed_location}{PARTITION_KEY}=${{{PARTITION_KEY}}}/"
                    ),
                },
                storage_descriptor=glue.CfnTable.StorageDescriptorProperty(
                    columns=[
                        glue.CfnTable.ColumnProperty(name=c["name"], type=c["type"])
                        for c in glue_columns()
                    ],
                    location=processed_location,
                    input_format="org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat",
                    output_format=(
                        "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"
                    ),
                    serde_info=glue.CfnTable.SerdeInfoProperty(
                        serialization_library=(
                            "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
                        )
                    ),
                ),
            ),
        )
        prices_table.add_resource_dependency(database)

        # ---------- Athena: workgroup with a per-query scan limit ----------
        athena.CfnWorkGroup(
            self,
            "AthenaWorkGroup",
            name="grocery-tracker",
            description="Queries for the grocery tracker",
            recursive_delete_option=True,
            work_group_configuration=athena.CfnWorkGroup.WorkGroupConfigurationProperty(
                enforce_work_group_configuration=True,
                bytes_scanned_cutoff_per_query=100 * 1024 * 1024,  # 100 MB guard rail
                result_configuration=athena.CfnWorkGroup.ResultConfigurationProperty(
                    output_location=f"s3://{bucket.bucket_name}/{ATHENA_PREFIX}"
                ),
            ),
        )

        # ---------- Budget: email when spend approaches the limit ----------
        subscriber = budgets.CfnBudget.SubscriberProperty(
            subscription_type="EMAIL", address=budget_email
        )
        budgets.CfnBudget(
            self,
            "MonthlyBudget",
            budget=budgets.CfnBudget.BudgetDataProperty(
                budget_name="grocery-tracker-monthly",
                budget_type="COST",
                time_unit="MONTHLY",
                budget_limit=budgets.CfnBudget.SpendProperty(amount=budget_limit_usd, unit="USD"),
            ),
            notifications_with_subscribers=[
                budgets.CfnBudget.NotificationWithSubscribersProperty(
                    notification=budgets.CfnBudget.NotificationProperty(
                        notification_type=kind,
                        comparison_operator="GREATER_THAN",
                        threshold=pct,
                        threshold_type="PERCENTAGE",
                    ),
                    subscribers=[subscriber],
                )
                for kind, pct in [("ACTUAL", 50), ("ACTUAL", 100), ("FORECASTED", 100)]
            ],
        )

        # ---------- Outputs: names you'll need in the terminal ----------
        CfnOutput(self, "BucketName", value=bucket.bucket_name)
        CfnOutput(self, "TransformFunctionName", value=transform_fn.function_name)
        CfnOutput(self, "TransformLogGroup", value=transform_logs.log_group_name)
        CfnOutput(self, "AthenaWorkGroupName", value="grocery-tracker")
