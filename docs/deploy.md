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

**1. Install Node.js (LTS).** CDK runs on Node. Use the official macOS installer from [nodejs.org](https://nodejs.org). On older macOS versions Homebrew has no prebuilt packages, so `brew install node` compiles LLVM and Rust from source, which takes hours and many GB of disk.
```bash
node --version
```

**2. Install the AWS CLI** (v2.32 or newer, which includes `aws login`).
```bash
brew install awscli
```

**3. Create an IAM user for yourself.** Do this once in the AWS console, signed in as root:
- Turn on MFA for the root user.
- Create an IAM user (e.g. `admin`) with console access and the `AdministratorAccess` policy, and turn on MFA for it too.
- Sign out of root and do everything else as this user. Never create access keys for root.

**4. Sign in from the CLI without long-lived keys.** `aws login` opens the browser and asks you to sign in as the IAM user. The CLI then receives short-lived credentials and keeps refreshing them while the session is valid. When a command says your session has expired, run it again.
```bash
aws login --profile grocery-tracker
```
Check you're the IAM user, not root. The ARN should end in `:user/<name>`:
```bash
aws sts get-caller-identity --profile grocery-tracker
```
> If your organisation uses IAM Identity Center, `aws configure sso --profile grocery-tracker` works too.

**5. Install the CDK Python libraries** into the project venv:
```bash
pip install -e ".[dev,infra]"
```

**6. Bootstrap CDK** (once per account and region). This creates a `CDKToolkit` stack with an S3 bucket for uploaded code and the IAM roles CDK deploys with. Cost is fractions of a cent.
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
The outputs print `BucketName`, `TransformFunctionName` and `TransformLogGroup`. A first deploy takes about 90 seconds.

AWS Budgets emails the alert address directly. It doesn't send a confirmation email first.

## Smoke test (first deploy)

Upload a two-row CSV to `raw/prices/date=2026-01-05/`, then check the logs and query Athena. Measured on the first deploy:

- The Lambda ran about 1 second after the upload: 2.1 s cold start, 1.0 s run, 210 MB of memory used out of 1024 MB.
- The Athena query scanned 686 bytes. Unit price and discount maths matched the local tests.

Then delete the test CSV **and** its `processed/.../part-0.parquet`. Deletes don't trigger the transform, so the processed file has to be removed by hand.

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
