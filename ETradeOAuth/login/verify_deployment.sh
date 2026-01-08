#!/bin/bash

# Easy OAuth Token Manager - Deployment Verification Script
# This script verifies the web app is ready for deployment

echo "🔍 Verifying Easy OAuth Token Manager Deployment Readiness"
echo "========================================================"

# Check if we're in the right directory
if [ ! -f "public/index.html" ]; then
    echo "❌ Error: public/index.html not found. Please run this script from the ETradeOAuth/login directory."
    exit 1
fi

echo "✅ Found main web app file: public/index.html"

# Check for required files
echo ""
echo "📋 Checking required files..."

required_files=(
    "public/index.html"
    "oauth_backend.py"
    "secret_manager_oauth.py"
    "store_tokens_etradestrategy.py"
    "firebase.json"
    ".firebaserc"
    "requirements.txt"
    "Dockerfile"
)

for file in "${required_files[@]}"; do
    if [ -f "$file" ]; then
        echo "✅ $file"
    else
        echo "❌ Missing: $file"
    fi
done

# Check for compliance features in index.html
echo ""
echo "🛡️ Checking Google Cloud AUP compliance features..."

compliance_checks=(
    "Easy OAuth Token Manager"
    "€£$¥ Trading Software Development Team"
    "Privacy Policy"
    "Compliance Notice"
    "Third-Party Service Disclosure"
    "google-site-verification"
    "X-Content-Type-Options"
    "X-Frame-Options"
    "X-XSS-Protection"
)

for check in "${compliance_checks[@]}"; do
    if grep -q "$check" public/index.html; then
        echo "✅ $check"
    else
        echo "❌ Missing: $check"
    fi
done

# Check API configuration
echo ""
echo "🔧 Checking API configuration..."

if grep -q "etrade-oauth-web-uc.a.run.app" public/index.html; then
    echo "✅ Backend API URL configured"
else
    echo "❌ Backend API URL not configured"
fi

if grep -q "GeCz-R-9p6GO5eSAnLloq4GAvvqGNwRRhM3REFwc0NI" public/index.html; then
    echo "✅ Google Search Console verification configured"
else
    echo "❌ Google Search Console verification not configured"
fi

# Check mobile responsiveness
echo ""
echo "📱 Checking mobile responsiveness..."

if grep -q "@media.*max-width.*768px" public/index.html; then
    echo "✅ Mobile responsive design implemented"
else
    echo "❌ Mobile responsive design not implemented"
fi

# Check deployment scripts
echo ""
echo "🚀 Checking deployment scripts..."

if [ -f "deploy_firebase.sh" ]; then
    echo "✅ Firebase deployment script ready"
else
    echo "❌ Firebase deployment script missing"
fi

if [ -f "deploy.sh" ]; then
    echo "✅ Backend deployment script ready"
else
    echo "❌ Backend deployment script missing"
fi

echo ""
echo "🎯 Deployment Readiness Summary:"
echo "================================"

if [ -f "public/index.html" ] && [ -f "oauth_backend.py" ] && [ -f "firebase.json" ]; then
    echo "✅ Web app is ready for deployment!"
    echo ""
    echo "📋 Next steps:"
    echo "1. Deploy backend: ./deploy.sh"
    echo "2. Deploy frontend: ./deploy_firebase.sh"
    echo "3. Test the deployed application"
    echo "4. Submit appeal if needed"
else
    echo "❌ Web app is not ready for deployment"
    echo "Please fix the missing files above"
fi

echo ""
echo "🌐 Expected URLs after deployment:"
echo "Frontend: https://etrade-oauth-manager.web.app"
echo "Backend: https://etrade-oauth-web-uc.a.run.app"

