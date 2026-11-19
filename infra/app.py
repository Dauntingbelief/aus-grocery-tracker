#!/usr/bin/env python3
"""CDK app entry point. Run from infra/:  npx aws-cdk@2 synth -c budget_email=you@example.com"""

import os

import aws_cdk as cdk

from grocery_infra.stack import GroceryTrackerStack

app = cdk.App()

budget_email = app.node.try_get_context("budget_email") or os.environ.get("BUDGET_ALERT_EMAIL")
if not budget_email:
    raise SystemExit(
        "Set the budget alert email: `-c budget_email=you@example.com` "
        "or BUDGET_ALERT_EMAIL in your shell/.env"
    )

GroceryTrackerStack(
    app,
    "GroceryTrackerStack",
    budget_email=budget_email,
    pandas_layer_version=int(app.node.try_get_context("pandas_layer_version")),
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=app.node.try_get_context("region"),
    ),
)
cdk.Tags.of(app).add("project", "grocery-tracker")

app.synth()
