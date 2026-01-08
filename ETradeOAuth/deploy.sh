#!/bin/bash

# OAuth Frontend Deployment Script
# Easy ORB Strategy - Rev 00231
# Last Updated: January 6, 2026

set -e

echo "🚀 Deploying OAuth Frontend to Firebase Hosting"
echo "📅 Date: $(date)"
echo "🔖 Version: Rev 00231"

# Check if .env exists
if [ ! -f .env ]; then
    echo "⚠️  .env file not found. Using defaults..."
    echo "💡 Create .env from .env.example for custom configuration"
fi

# Install dependencies
echo "📦 Installing dependencies..."
npm install

# Build frontend
echo "🏗️  Building frontend..."
npm run build

# Check if build succeeded
if [ ! -d "dist" ]; then
    echo "❌ Build failed - dist directory not found"
    exit 1
fi

# Deploy to Firebase
echo "🚀 Deploying to Firebase..."
firebase deploy --only hosting

echo "✅ Deployment complete!"
echo "🌐 Frontend URL: https://easy-trading-oauth-v2.web.app"
echo "🔐 Management Portal: https://easy-trading-oauth-v2.web.app/manage.html"

