# Deploying to AWS

Everything is defined in `infra/` with AWS CDK (Python). Region: `ap-southeast-2` (Sydney).

## What gets created

| Resource | What it's for | Expected cost |
|---|---|---|
| S3 bucket (private, encrypted, TLS-only) | `raw/` CSVs, `processed/` Parquet, `reference/basket.csv`, `athena-results/` (auto-deleted after 7 days) | < $0.01/mo (a few MB) |
| Lambda `TransformFunction` (Python 3.12) | Runs when a CSV lands in `raw/prices/` and rebuilds the Parquet | Free tier (1M requests/mo, always free) |
| AWS SDK for pandas layer | AWS-published pandas + pyarrow, so we don't bundle 100 MB of dependencies | Free |
| Glue database + `prices` table | Schema for Athena. Partition projection means no crawler ($0.44/hr) is needed | Free (under 1M catalog objects) |
| Athena workgroup | SQL over the Parquet, with a 100 MB per-query scan limit | $5/TB scanned; our queries cost about $0.00005 each |
| CloudWatch log group | Lambda logs, kept for 14 days | Free tier (5 GB) |
| AWS Budgets | Emails you at 50% and 100% of $5 actual spend, and at 100% forecast | Free |
| CDK helper Lambdas | Upload the basket, wire up S3 events, empty the bucket on destroy | Free tier |

**Expected total: well under $0.10/month.** The budget is in **USD**, because AWS bills in USD.

## One-time setup

**1. Fix Node.js.** CDK runs on Node. Homebrew's node is currently broken on this Mac because of a missing `llhttp` library.

```bash
brew update && brew upgrade node
```
```bash
node --version
```

**2. Install the AWS CLI.**
```bash
brew install awscli
```

**3. Sign in without long-lived keys.** In the AWS console, enable **IAM Identity Center**, create a user for yourself, and give it the `AdministratorAccess` permission set on your account. Don't use the root user. Then:
```bash
aws configure sso --profile grocery-tracker
```
```bash
aws sts get-caller-identity --profile grocery-tracker
```

**4. Install the CDK Python libraries** into the project venv:
```bash
pip install -e ".[dev,infra]"
```

**5. Bootstrap CDK** (once per account and region). This creates a `CDKToolkit` stack with an S3 bucket for uploaded code and the IAM roles CDK deploys with. Cost is fractions of a cent.
```bash
cd infra && npx aws-cdk@2 bootstrap --profile grocery-tracker
```

## Deploy

Preview what will change before deploying. The diff shows every resource and every IAM permission:
```bash
npx aws-cdk@2 diff --profile grocery-tracker -c budget_email=YOUR_EMAIL
```
```bash
npx aws-cdk@2 deploy --profile grocery-tracker -c budget_email=YOUR_EMAIL
```
The outputs print `BucketName`, `TransformFunctionName` and `TransformLogGroup`.

## Weekly use

Upload this week's CSV. The upload triggers the transform automatically:
```bash
aws s3 sync data/raw/prices s3://BUCKET_NAME/raw/prices/ --exclude "*.gitkeep" --profile grocery-tracker
```
Check that it ran:
```bash
aws logs tail LOG_GROUP_NAME --since 10m --profile grocery-tracker
```
Then query in the Athena console (choose workgroup `grocery-tracker`):
```sql
SELECT cpi_group_name, count(*) AS items, round(avg(discount_pct), 3) AS avg_discount
FROM grocery_tracker.prices
WHERE is_promo
GROUP BY 1 ORDER BY 3 DESC;
```

## Tear down

Deletes everything, including the bucket contents. Your raw CSVs are safe in git.
```bash
npx aws-cdk@2 destroy --profile grocery-tracker -c budget_email=YOUR_EMAIL
```

## Design notes (interview talking points)

- **Event-driven, not scheduled:** prices arrive when you upload them, so an S3 event trigger fits better than a cron job. EventBridge comes in milestone 4, for the ABS CPI pull, which does run on a schedule.
- **Full rebuild on every upload:** about 60 rows a week means reprocessing everything takes about a second. In return the job is idempotent, so re-uploads, corrections and duplicate events all give the same result.
- **Partition projection rather than crawlers:** the table definition tells Athena where each month's data lives, so there's no crawler to pay for or run.
- **One schema definition:** `src/grocery_tracker/schema.py` drives both the Parquet writer and the Glue table, and a test fails if they drift apart.
- **Least-privilege IAM:** the Lambda can read `raw/` and `reference/` and write only to `processed/`.
- **Tested infrastructure:** `tests/test_infra.py` synthesises the stack and checks for a private bucket, the $5 budget, the 100 MB scan limit and log retention.
