#!/bin/bash

# Easy OAuth Token Manager - Backend Deployment Script
# This script deploys the OAuth backend API to Google Cloud Run

set -e

# Configuration
PROJECT_ID=${GCP_PROJECT:-"easy-etrade-strategy"}
REGION=${GCP_REGION:-"us-central1"}
SERVICE_NAME="easy-etrade-strategy-oauth"
IMAGE_NAME="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"

echo "🚀 Deploying Easy OAuth Token Manager Backend to Google Cloud Run"
echo "Project: ${PROJECT_ID}"
echo "Region: ${REGION}"
echo "Service: ${SERVICE_NAME}"

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
gcloud services enable cloudbuild.googleapis.com
gcloud services enable run.googleapis.com
gcloud services enable secretmanager.googleapis.com
gcloud services enable pubsub.googleapis.com

# Build and push the container
echo "🏗️  Building and pushing container..."
gcloud builds submit --tag ${IMAGE_NAME} .

# Deploy to Cloud Run
echo "🚀 Deploying to Cloud Run..."
gcloud run deploy ${SERVICE_NAME} \
    --image ${IMAGE_NAME} \
    --region ${REGION} \
    --platform managed \
    --allow-unauthenticated \
    --memory 512Mi \
    --cpu 1 \
    --max-instances 10 \
    --set-env-vars "GCP_PROJECT=${PROJECT_ID},APP_BASE_URL=https://${SERVICE_NAME}-${REGION}.a.run.app"

# Get the service URL
SERVICE_URL=$(gcloud run services describe ${SERVICE_NAME} --region=${REGION} --format="value(status.url)")

echo "✅ Deployment complete!"
echo "🌐 Service URL: ${SERVICE_URL}"
echo ""
echo "📝 Next steps:"
echo "1. Set up your Telegram bot and get the bot token and chat ID"
echo "2. Store your E*TRADE consumer keys in Secret Manager:"
echo "   - etrade/prod/consumer_key"
echo "   - etrade/prod/consumer_secret"
echo "   - etrade/sandbox/consumer_key"
echo "   - etrade/sandbox/consumer_secret"
echo "3. Set up Cloud Scheduler to call ${SERVICE_URL}/cron/morning-alert at 8:30 AM ET"
echo "4. Configure your trading service to subscribe to the 'token-rotated' Pub/Sub topic"
echo ""
echo "🔗 Admin URL: ${SERVICE_URL}/admin/secrets"
echo "🔗 OAuth Start: ${SERVICE_URL}/oauth/start?env=prod"

