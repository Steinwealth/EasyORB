#!/bin/bash

# Cloud Scheduler Setup Script for OAuth Keepalive System
# This script sets up persistent keepalive that runs independently of the web app

set -e

# Configuration
PROJECT_ID=${GCP_PROJECT:-"easy-strategy-oauth"}
REGION=${GCP_REGION:-"us-central1"}
BACKEND_URL="https://easy-strategy-oauth-backend-763976537415.us-central1.run.app"

echo "🚀 Setting up Cloud Scheduler for OAuth Keepalive System"
echo "Project: ${PROJECT_ID}"
echo "Region: ${REGION}"
echo "Backend URL: ${BACKEND_URL}"

# Check if gcloud is installed and authenticated
if ! command -v gcloud &> /dev/null; then
    echo "❌ gcloud CLI is not installed. Please install it first."
    exit 1
fi

# Set the project
echo "📋 Setting project to ${PROJECT_ID}..."
gcloud config set project ${PROJECT_ID}

# Enable required APIs
echo "🔧 Enabling required APIs..."
gcloud services enable cloudscheduler.googleapis.com
gcloud services enable cloudbuild.googleapis.com
gcloud services enable run.googleapis.com
gcloud services enable secretmanager.googleapis.com

# Create Cloud Scheduler jobs
echo "⏰ Creating Cloud Scheduler jobs..."

# Job 1: Keepalive Production Tokens (every hour at minute 0)
echo "📅 Creating production keepalive job..."
gcloud scheduler jobs create http oauth-keepalive-prod \
    --location="${REGION}" \
    --schedule="0 * * * *" \
    --time-zone="America/New_York" \
    --uri="${BACKEND_URL}/api/keepalive/force/prod" \
    --http-method=POST \
    --headers="Content-Type=application/json" \
    --message-body="{}" \
    --description="Keep production OAuth tokens alive every hour"

# Job 2: Keepalive Sandbox Tokens (every hour at minute 30)
echo "📅 Creating sandbox keepalive job..."
gcloud scheduler jobs create http oauth-keepalive-sandbox \
    --location="${REGION}" \
    --schedule="30 * * * *" \
    --time-zone="America/New_York" \
    --uri="${BACKEND_URL}/api/keepalive/force/sandbox" \
    --http-method=POST \
    --headers="Content-Type=application/json" \
    --message-body="{}" \
    --description="Keep sandbox OAuth tokens alive every hour (offset by 30 minutes)"

# Job 3: Health Check (every hour at minute 15)
echo "📅 Creating health check job..."
gcloud scheduler jobs create http oauth-health-check \
    --location="${REGION}" \
    --schedule="15 * * * *" \
    --time-zone="America/New_York" \
    --uri="${BACKEND_URL}/healthz" \
    --http-method=GET \
    --description="Health check for OAuth backend every hour"

# List created jobs
echo "📋 Created Cloud Scheduler jobs:"
gcloud scheduler jobs list

echo ""
echo "✅ Cloud Scheduler setup complete!"
echo ""
echo "📊 Keepalive Schedule:"
echo "   • Production: Every 80 minutes"
echo "   • Sandbox: Every 80 minutes (offset by 10 minutes)"
echo "   • Health Check: Every hour"
echo ""
echo "🎯 Benefits:"
echo "   ✅ Persistent keepalive independent of web app"
echo "   ✅ Runs even when browser is closed"
echo "   ✅ Maintains tokens for full 24-hour lifecycle"
echo "   ✅ Prevents E*TRADE 2-hour idle timeout"
echo ""
echo "🔍 To monitor jobs:"
echo "   gcloud scheduler jobs list"
echo "   gcloud scheduler jobs describe oauth-keepalive-prod"
echo "   gcloud scheduler jobs describe oauth-keepalive-sandbox"
echo ""
echo "🛑 To stop jobs (if needed):"
echo "   gcloud scheduler jobs pause oauth-keepalive-prod"
echo "   gcloud scheduler jobs pause oauth-keepalive-sandbox"
echo "   gcloud scheduler jobs pause oauth-health-check"

