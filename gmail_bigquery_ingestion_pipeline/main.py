"""
Cloud Function entry point for the daily sales ingestion pipeline.

Triggered by Cloud Scheduler via HTTP (unauthenticated calls are blocked
at the function level — Cloud Scheduler uses OIDC tokens).

Deploy command:
    gcloud functions deploy ecom-sales-ingestion \
        --gen2 \
        --runtime=python311 \
        --region=us-central1 \
        --source=. \
        --entry-point=ingest \
        --trigger-http \
        --no-allow-unauthenticated \
        --set-secrets="GMAIL_EMAIL=gmail-email:latest,GMAIL_APP_PASSWORD=gmail-app-password:latest" \
        --set-env-vars="BQ_PROJECT_ID=YOUR_PROJECT,BQ_DATASET_ID=raw,BQ_RAW_TABLE=raw_orders" \
        --timeout=300s \
        --memory=512Mi

Cloud Scheduler setup (runs daily after email received in the morning — adjust schedule as needed):
    gcloud scheduler jobs create http ecom-ingestion-trigger \
        --schedule="0 7 * * *" \
        --uri="https://REGION-PROJECT_ID.cloudfunctions.net/ecom-sales-ingestion" \
        --http-method=POST \
        --oidc-service-account-email=YOUR_SA@PROJECT_ID.iam.gserviceaccount.com
"""

import functions_framework

from utils.alerting import send_failure_alert, send_no_email_alert
from utils.attachment_parser import NoAttachmentError
from utils.config import Config
from utils.gmail_reader import NoMatchingEmailError
from utils.logging_config import setup_logging
from utils.pipeline import run

setup_logging()


@functions_framework.http
def ingest(request):
    """HTTP Cloud Function — called by Cloud Scheduler daily."""
    config = None
    try:
        config = Config.from_env()
        run(config)
        return {"status": "success"}, 200
    except NoMatchingEmailError as exc:
        if config:
            send_no_email_alert(config)
        return {"status": "no_email", "message": str(exc)}, 200  # not a 5xx — expected condition
    except NoAttachmentError as exc:
        # send_no_attachment_alert already called inside run()
        return {"status": "no_attachment", "message": str(exc)}, 200
    except Exception as exc:
        if config:
            send_failure_alert(config, exc)
        return {"status": "error", "message": str(exc)}, 500