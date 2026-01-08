# ETradeOAuth - OAuth Token Management Frontend

**Last Updated**: January 6, 2026  
**Version**: Rev 00231 (Trade ID Shortening & Alert Formatting Improvements)  
**Status**: ✅ **PRODUCTION ACTIVE**  
**Live URL**: https://easy-trading-oauth-v2.web.app

## Overview

This folder contains the **frontend web application** for managing E*TRADE OAuth tokens. The application provides a secure, mobile-friendly interface for daily token renewal.

**Note**: This directory contains only the frontend Firebase Hosting deployment. Backend OAuth modules (Python) are deployed separately as a Cloud Run service. The backend API endpoint is: `https://easy-etrade-strategy-oauth-223967598315.us-central1.run.app`

## 🏗️ Project Structure

```
ETradeOAuth/
├── public/
│   ├── index.html          # Public dashboard
│   ├── manage.html         # Private management portal
│   └── assets/             # Static assets
├── src/
│   ├── components/         # React/Vue components (if using framework)
│   ├── utils/              # Utility functions
│   └── styles/             # CSS styles
├── .env                    # Environment variables (not in git, create from .env.example)
├── .env.example            # Environment template (✅ present)
├── tokens_prod.json        # Production OAuth tokens (gitignored, local dev only)
├── tokens_sandbox.json     # Sandbox OAuth tokens (gitignored, local dev only)
├── firebase.json           # Firebase configuration
├── package.json            # Dependencies
├── vite.config.js          # Vite configuration (if using Vite)
└── README.md               # This file
```

## 🚀 Quick Start

### Installation

```bash
# Navigate to ETradeOAuth directory
cd ETradeOAuth

# Install dependencies
npm install

# Create environment file
# Create .env file with the following content:
# VITE_OAUTH_BACKEND_URL=https://easy-etrade-strategy-oauth-223967598315.us-central1.run.app
# VITE_TIMEZONE=America/New_York
# VITE_TOKEN_EXPIRY_HOURS=24
# VITE_MANAGE_PORTAL_PASSWORD=easy2025
```

### Development

```bash
# Start development server
npm run dev

# Build for production
npm run build

# Preview production build
npm run preview
```

### Deployment

```bash
# Deploy to Firebase
firebase deploy --only hosting
```

## 🌐 Live Deployment

- **Public Dashboard**: https://easy-trading-oauth-v2.web.app
- **Management Portal**: https://easy-trading-oauth-v2.web.app/manage.html (Access: easy2025)
- **OAuth Backend**: https://easy-etrade-strategy-oauth-223967598315.us-central1.run.app

## 📋 Features

- ✅ Public dashboard (information only)
- ✅ Private management portal (password protected)
- ✅ Real-time countdown timer
- ✅ Token status dashboard
- ✅ Mobile-responsive design
- ✅ Anti-phishing security architecture
- ✅ Google Cloud compliance

## 🔐 Security

- **Public Dashboard**: No credential forms, safe for indexing
- **Management Portal**: Password protected (easy2025), not indexed
- **OAuth Flow**: PIN input only on private portal
- **HTTPS**: All traffic encrypted
- **Token Files**: `tokens_prod.json` and `tokens_sandbox.json` are gitignored (never commit OAuth tokens)
  - These files are for local development/testing only
  - In production, tokens are stored securely in Google Cloud Secret Manager
  - If you need these files locally, create them manually (they will be gitignored)

## 📚 Documentation

For complete deployment and configuration details, see:
- [ANTI_PHISHING_ARCHITECTURE.md](./ANTI_PHISHING_ARCHITECTURE.md) - Anti-phishing security architecture (✅ present)
- [docs/Firebase.md](../docs/Firebase.md) - Firebase deployment guide
- [docs/OAuth.md](../docs/OAuth.md) - OAuth token management guide

---

*Last Updated: January 6, 2026*  
*Version: Rev 00231*

