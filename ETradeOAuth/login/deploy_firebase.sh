#!/bin/bash

# Firebase Hosting Deployment Script for E*TRADE OAuth Web App
# This script deploys the OAuth web app to Firebase Hosting

set -e

echo "🚀 Deploying E*TRADE OAuth Web App to Firebase Hosting..."

# Check if Firebase CLI is installed
if ! command -v firebase &> /dev/null; then
    echo "❌ Firebase CLI not found. Installing..."
    npm install -g firebase-tools
fi

# Check if user is logged in to Firebase
if ! firebase projects:list &> /dev/null; then
    echo "🔐 Please log in to Firebase..."
    firebase login
fi

# Initialize Firebase project if not already done
if [ ! -f "firebase.json" ]; then
    echo "📝 Initializing Firebase project..."
    firebase init hosting
fi

# Build the web app
echo "🔨 Building web app..."
# The web app is already in public/index.html (compliant version)

# Deploy to Firebase
echo "🚀 Deploying to Firebase Hosting..."
firebase deploy --only hosting

echo "✅ Deployment complete!"
echo "🌐 Your OAuth web app is now live at:"
echo "   https://etrade-oauth-manager.web.app"

echo ""
echo "📱 Google Cloud AUP Compliant OAuth token management is now available!"
echo "🔐 Use this interface to renew E*TRADE tokens daily"
echo "⏰ Countdown timer shows time until next renewal required"
echo "🔄 Professional interface with complete compliance measures"
echo ""
echo "🎯 Compliance Features:"
echo "   ✅ Clear branding and developer identification"
echo "   ✅ Complete privacy policy and data usage transparency"
echo "   ✅ Anti-phishing measures implemented"
echo "   ✅ Professional security headers and meta tags"
echo "   ✅ Mobile responsive design"

