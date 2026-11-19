"""CDK assertion tests: synthesise the stack in memory and check the CloudFormation template.

These catch infra mistakes (public bucket, missing budget, schema drift) before `cdk deploy`.
Skipped automatically if the CDK libraries aren't installed (`pip install -e ".[infra]"`).
"""

import pytest

cdk = pytest.importorskip("aws_cdk")
from aws_cdk.assertions import Match, Template  # noqa: E402

from grocery_tracker.schema import glue_columns  # noqa: E402


@pytest.fixture(scope="module")
def template() -> Template:
    from grocery_infra.stack import GroceryTrackerStack

    app = cdk.App()
    stack = GroceryTrackerStack(
        app,
        "TestStack",
        budget_email="alerts@example.com",
        env=cdk.Environment(account="123456789012", region="ap-southeast-2"),
    )
    return Template.from_stack(stack)


def test_bucket_is_private_and_encrypted(template):
    template.has_resource_properties(
        "AWS::S3::Bucket",
        {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "BlockPublicPolicy": True,
                "IgnorePublicAcls": True,
                "RestrictPublicBuckets": True,
            },
            "BucketEncryption": Match.object_like({}),
        },
    )
    # enforce_ssl adds a Deny for non-TLS requests
    template.has_resource_properties(
        "AWS::S3::BucketPolicy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Effect": "Deny",
                                "Condition": {"Bool": {"aws:SecureTransport": "false"}},
                            }
                        )
                    ]
                )
            }
        },
    )


def test_transform_lambda(template):
    template.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "Handler": "grocery_tracker.aws.transform_handler.handler",
            "Runtime": "python3.12",
            "Layers": [
                "arn:aws:lambda:ap-southeast-2:336392948345:layer:AWSSDKPandas-Python312:32"
            ],
            "Environment": {
                "Variables": Match.object_like(
                    {"RAW_PREFIX": "raw/prices/", "PROCESSED_PREFIX": "processed/prices/"}
                )
            },
        },
    )
    template.has_resource_properties("AWS::Lambda::EventInvokeConfig", {"MaximumRetryAttempts": 0})


def test_s3_event_triggers_transform_on_raw_csv(template):
    template.has_resource_properties(
        "Custom::S3BucketNotifications",
        {
            "NotificationConfiguration": {
                "LambdaFunctionConfigurations": [
                    Match.object_like(
                        {
                            "Events": ["s3:ObjectCreated:*"],
                            "Filter": {
                                "Key": {
                                    "FilterRules": Match.array_with(
                                        [
                                            {"Name": "suffix", "Value": ".csv"},
                                            {"Name": "prefix", "Value": "raw/prices/"},
                                        ]
                                    )
                                }
                            },
                        }
                    )
                ]
            }
        },
    )


def test_glue_table_matches_parquet_schema(template):
    tables = template.find_resources("AWS::Glue::Table")
    (table,) = tables.values()
    table_input = table["Properties"]["TableInput"]
    assert table_input["StorageDescriptor"]["Columns"] == [
        {"Name": c["name"], "Type": c["type"]} for c in glue_columns()
    ]
    assert table_input["PartitionKeys"] == [{"Name": "year_month", "Type": "string"}]
    assert table_input["Parameters"]["projection.enabled"] == "true"


def test_athena_workgroup_has_scan_limit(template):
    template.has_resource_properties(
        "AWS::Athena::WorkGroup",
        {
            "WorkGroupConfiguration": Match.object_like(
                {"BytesScannedCutoffPerQuery": 100 * 1024 * 1024}
            )
        },
    )


def test_budget_alert_at_5_usd(template):
    template.has_resource_properties(
        "AWS::Budgets::Budget",
        {
            "Budget": Match.object_like(
                {"BudgetLimit": {"Amount": 5, "Unit": "USD"}, "TimeUnit": "MONTHLY"}
            ),
            "NotificationsWithSubscribers": Match.array_with(
                [
                    Match.object_like(
                        {
                            "Subscribers": [
                                {"SubscriptionType": "EMAIL", "Address": "alerts@example.com"}
                            ]
                        }
                    )
                ]
            ),
        },
    )


def test_logs_expire(template):
    template.has_resource_properties("AWS::Logs::LogGroup", {"RetentionInDays": 14})
