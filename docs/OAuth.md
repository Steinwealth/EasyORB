# 🔐 E*TRADE OAuth Token Management Guide - Easy ORB Strategy

**Last Updated**: January 6, 2026  
**Version**: Rev 00231 (Trade ID Shortening & Alert Formatting Improvements)  
**Status**: ✅ **PRODUCTION ACTIVE** - Optimized Deployment

## Overview

The E*TRADE OAuth system is **critical** for continuous trading operations. E*TRADE tokens expire at **midnight ET every day** and require daily renewal to maintain uninterrupted trading. This comprehensive guide covers all aspects of OAuth token acquisition, management, and automated renewal.

**Current Integration**: Fully integrated with Cloud Scheduler keep-alive system to ensure trading system is always running during critical windows.

---

## 🌐 **Live System Status**

| Component | Status | URL/Details |
|-----------|--------|-------------|
| **Firebase Web App** | ✅ **LIVE** (Anti-Phishing Secure) | https://easy-trading-oauth-v2.web.app |
| **Management Portal** | 🦜💼 **PRIVATE** | https://easy-trading-oauth-v2.web.app/manage.html (Access: easy2025) |
| **OAuth Backend** | ✅ **LIVE** (1 vCPU, 512Mi) | https://easy-etrade-strategy-oauth-223967598315.us-central1.run.app |
| **Main Trading System** | ✅ **LIVE** (Cloud Run, min-instances=1) | https://easy-etrade-strategy-223967598315.us-central1.run.app |
| **Secret Manager** | ✅ **CONFIGURED** | Google Cloud Secret Manager active |
| **OAuth Integration** | ✅ **READY** | Complete token management system |
| **Alert System** | ✅ **ACTIVE** | Telegram alerts via direct API (24/7 availability) |
| **Token Storage** | ✅ **SECURE** | Encrypted storage in Secret Manager |
| **Keepalive System** | ✅ **AUTOMATED** | Cloud Scheduler hourly jobs (prod :00, sandbox :30) |
| **Midnight Alert** | ✅ **ENABLED** | Consolidated expiry alert at 12:00 AM ET |
| **Renewal Alerts** | ✅ **ENABLED** | Immediate confirmation via Telegram |
| **Mobile Interface** | ✅ **LIVE** | Mobile-friendly web app deployed |
| **Google Compliance** | ✅ **FULLY COMPLIANT** | Complete AUP compliance implemented |
| **Anti-Phishing Measures** | ✅ **IMPLEMENTED** | Complete transparency and legitimate identification |
| **Portal Flexibility** | ✅ **ENABLED** | Either portal URL can renew either token |
| **Cost Optimization** | ✅ **COMPLETED** | 93% cost reduction (~$11/month total) |

---

## ⚠️ **CRITICAL: Daily Token Renewal Required**

### **Token Lifecycle Rules**
- **Daily Expiry**: E*TRADE tokens expire at **midnight ET every day**
- **Idle Timeout**: Tokens become inactive after **2 hours** of no API calls
- **Renewal Window**: Inactive tokens can be renewed (no re-authorization needed)
- **Expiration**: Expired tokens require full re-authentication

### **Why This Matters**
- **Trading Interruption**: Expired tokens will stop all trading operations
- **Position Risk**: Open positions cannot be managed without valid tokens
- **Data Access**: Market data and account information become unavailable
- **Revenue Loss**: Missed trading opportunities during token downtime

---

## 🏗️ OAuth Architecture

### **ETradeOAuth System Components**

#### **Cloud Deployment (Primary)**
```
Production OAuth System:
├── Firebase Frontend (https://easy-trading-oauth-v2.web.app)
│   ├── index.html                    # Public dashboard
│   └── manage.html                   # Token management portal (Access: easy2025)
│
├── OAuth Backend (Cloud Run: easy-etrade-strategy-oauth)
│   ├── oauth_web_app.py              # FastAPI backend with Telegram alerts
│   ├── Secret Manager integration    # Token storage and retrieval
│   └── Direct Telegram API           # Alert delivery (24/7)
│
└── Cloud Scheduler Jobs
    ├── oauth-midnight-alert          # 12:00 AM ET daily → OAuth backend
    ├── oauth-keepalive-prod          # Hourly at :00
    └── oauth-keepalive-sandbox       # Hourly at :30

NOTE: All systems run on Cloud Run for true 24/7 operation (Demo and Live modes)
```

#### **Local Development Components**
```
ETradeOAuth/ (Local Development)
├── login/                           # Frontend deployment directory
│   ├── public/                     # Static HTML files
│   │   ├── index.html              # Public dashboard
│   │   ├── manage.html             # Private management portal
│   │   └── *.html                  # Other files
│   ├── firebase.json               # Firebase configuration
│   ├── deploy_firebase.sh          # Deployment script
│   ├── oauth_backend.py            # FastAPI backend
│   ├── secret_manager_oauth.py     # Secret Manager integration
│   ├── keepalive_oauth.py          # Keepalive system
│   ├── functions/                   # Cloud Functions
│   └── requirements.txt            # Python dependencies
├── modules/                         # Python OAuth modules
│   ├── account_balance_checker.py
│   ├── central_oauth_manager.py
│   ├── etrade_oauth_manager.py
│   ├── etrade_trading_integration.py
│   ├── enhanced_oauth_alerts.py
│   ├── simple_oauth_cli.py
│   └── strategy_oauth_integration.py
├── README.md                        # Documentation
├── ANTI_PHISHING_ARCHITECTURE.md    # Security documentation
└── .gitignore                       # Git ignore rules
```

---

### **🔐 Google Secret Manager Integration**

#### **Secret Structure**
```
Project: easy-etrade-strategy (223967598315)
Secrets:
  ├── etrade-oauth-sandbox          # Sandbox environment tokens
  ├── etrade-oauth-prod             # Production environment tokens
  ├── etrade-sandbox-consumer-key   # Sandbox consumer key
  ├── etrade-sandbox-consumer-secret # Sandbox consumer secret
  ├── etrade-prod-consumer-key      # Production consumer key
  ├── etrade-prod-consumer-secret   # Production consumer secret
  ├── telegram-bot-token            # Telegram bot token (for alerts)
  └── telegram-chat-id              # Telegram chat ID (for alerts)
```

**Note**: Telegram credentials are stored in Secret Manager and used by the OAuth backend service to send renewal confirmation alerts via direct Telegram API.

#### **Token Storage Format**
```json
{
  "oauth_token": "oauth_access_token",
  "oauth_token_secret": "oauth_access_secret",
  "created_at": "2026-01-06T16:21:19.899869+00:00",
  "last_used": "2026-01-06T16:21:19.899869+00:00",
  "stored_at": "2026-01-06T16:21:19.899869+00:00",
  "environment": "prod",
  "project_id": "easy-etrade-strategy",
  "expires_at": "2026-01-06T23:59:59.899341+00:00"
}
```

#### **Credential Storage Format**
```
Consumer Key Secret: "your_consumer_key_here"
Consumer Secret Secret: "your_consumer_secret_here"
```

#### **Secret Manager Benefits**
- **🔒 Encrypted Storage**: All credentials and tokens encrypted at rest
- **🛡️ IAM Control**: Fine-grained access control with service accounts
- **🔄 Versioning**: Automatic secret versioning for rollback capability
- **📊 Audit Logs**: Complete access logging and monitoring
- **🌐 Global Access**: Access from any Google Cloud service
- **💰 Cost Effective**: Free tier includes 6 secrets, 10K versions
- **🚀 Production Ready**: Integrated with Firebase frontend for daily renewal

---

## 🌐 Live Web App Usage

### **Access the OAuth Web App**
- **Public Dashboard**: https://easy-trading-oauth-v2.web.app
- **Management Portal**: https://easy-trading-oauth-v2.web.app/manage.html (Access: easy2025)
- **Mobile**: Fully responsive, works on all devices
- **Features**: Countdown timer, status monitoring, private token renewal
- **Compliance**: Fully compliant with Google Cloud Acceptable Use Policy (Anti-Phishing Secure)

### **Daily Token Renewal Process (Anti-Phishing Secure)**
1. **Visit Public Dashboard**: https://easy-trading-oauth-v2.web.app
2. **Check Status**: View current token status and countdown
3. **Click Renewal Button**: "Renew Production" or "Renew Sandbox"
4. **Redirect to Management Portal**: /manage.html?env=prod
5. **Enter Access Code**: easy2025 (password-protected)
6. **Complete OAuth Flow**: PIN authorization on private portal
7. **Automatic Storage**: Tokens saved to Google Secret Manager
8. **Confirmation**: Success alert sent via Telegram

### **Web App Features**
- **⏰ Countdown Timer**: Real-time countdown to midnight ET
- **📊 Status Dashboard**: Live OAuth system status for both Production and Sandbox
- **🔄 Dual Token Renewal**: Renew Production and/or Sandbox from any portal URL
- **📱 Mobile Optimized**: Perfect on phones and tablets
- **🔔 Telegram Alerts**: Immediate confirmation alerts via direct Telegram API
- **🔒 Portal Flexibility**: Either portal URL can renew either token
- **📡 24/7 Availability**: Alerts work regardless of trading system state
- **🔔 Real-time Updates**: Live status monitoring with automatic refresh

---

## 🔄 OAuth Flow Types

### **OAuth 1.0a Flow (Current Implementation)**

The Easy ORB Strategy uses **OAuth 1.0a** (3-legged OAuth) for E*TRADE API authentication:

1. **Request Token**: Get temporary request token from E*TRADE
2. **User Authorization**: User authorizes application on E*TRADE website
3. **Access Token**: Exchange authorized request token for access token
4. **API Access**: Use access token for all API calls

### **Token Types**

#### **Request Token** (Temporary)
- Used only during authorization flow
- Expires immediately after authorization
- Cannot be used for API calls

#### **Access Token** (Permanent)
- Used for all API calls
- Expires at midnight ET daily
- Can be renewed without re-authorization (if not expired)

---

## 🎯 Best Practices

### **Daily Operations**

#### **🌐 Live Web App Operations (Anti-Phishing Secure)**

##### **Current Deployment Status**
- **Web App**: https://easy-trading-oauth-v2.web.app ✅ **LIVE** (Anti-Phishing Secure)
- **Management Portal**: https://easy-trading-oauth-v2.web.app/manage.html 🦜💼 **PRIVATE** (Access: easy2025)
- **Secret Manager**: Google Cloud Secret Manager ✅ **CONFIGURED**
- **Alert System**: Telegram notifications ✅ **ACTIVE**
- **Mobile Interface**: Responsive design ✅ **WORKING**
- **Security Architecture**: Two-tier design ✅ **ANTI-PHISHING**

##### **Daily Token Renewal (Secure Process)**
1. **Token Expiry Alert**: Telegram notification at 12:00 AM ET (midnight when tokens expire)
2. **Visit Public Dashboard**: https://easy-trading-oauth-v2.web.app
3. **Check Token Status**: View Production/Sandbox validity indicators
4. **Click Renewal Button**: "Renew Production" and/or "Renew Sandbox"
5. **Access Private Portal**: Redirects to /manage.html?env=prod or /manage.html?env=sandbox
6. **Enter Access Code**: easy2025 (password-protected portal access)
7. **Select Token to Renew**: Click "Renew Production" or "Renew Sandbox" on portal
8. **OAuth Flow Starts**: Automatically begins E*TRADE authorization
9. **Authorize on E*TRADE**: Click link to complete authorization on E*TRADE website
10. **Copy PIN**: Get 6-digit PIN from E*TRADE authorization page
11. **Paste PIN**: Return to portal and enter PIN to complete OAuth
12. **Automatic Storage**: Fresh tokens stored in Google Secret Manager
13. **Telegram Confirmation**: Immediate alert sent via Telegram (Production or Sandbox)
14. **System Integration**: Trading system automatically loads tokens from Secret Manager
15. **Trading Ready**: System continues - no restart required

**Portal Flexibility**: Either portal URL (/manage.html?env=prod or /manage.html?env=sandbox) can renew either token (Production or Sandbox). The Telegram alert you receive matches the token you actually renewed, not the URL you accessed.

**Security Note**: All PIN input and credential collection happens on the private, password-protected management portal (/manage.html) that is NOT indexed by search engines, preventing Google Safe Browsing phishing detection.

**Alert Delivery**: OAuth renewal alerts are sent via direct Telegram API and work 24/7, regardless of whether the trading system is actively running.

#### **Morning Checklist**
1. **Check Token Status**: Verify tokens are active
2. **Renew if Needed**: Get fresh tokens if expired
3. **Test Connection**: Verify API connectivity
4. **Start Keepalive**: Begin token maintenance
5. **Monitor Alerts**: Watch for OAuth issues

#### **Evening Checklist**
1. **Check Token Health**: Verify tokens are still valid
2. **Review Logs**: Check for any OAuth errors
3. **Prepare for Renewal**: Ensure renewal process is ready
4. **Backup Tokens**: Save current token state

---

## 🚨 Emergency Procedures

### **Token Emergency Recovery**

#### **Complete System Failure**
```bash
# 1. Stop all trading operations
pkill -f "main.py"
pkill -f "scanner"

# 2. Emergency token renewal via web app
# Visit: https://easy-trading-oauth-v2.web.app/manage.html
# Enter access code: easy2025
# Renew Production and Sandbox tokens

# 3. Test all connections
# Check web app status dashboard

# 4. Restart trading system
# System will automatically load tokens from Secret Manager
```

#### **Partial Token Failure**
```bash
# 1. Identify failed environment via web app
# Visit: https://easy-trading-oauth-v2.web.app
# Check status dashboard

# 2. Renew specific environment via web app
# Click "Renew Production" or "Renew Sandbox"

# 3. Verify renewal via Telegram alert
# Should receive confirmation alert

# 4. Verify trading system
# System automatically loads fresh tokens from Secret Manager
```

---

## 📊 Integration with Trading System

### **Token Loading** (Rev 00190)

The trading system automatically loads tokens from Google Secret Manager:

```python
# Token loading happens automatically in prime_etrade_trading.py
def _load_tokens_from_secret_manager(self) -> Optional[Dict[str, Any]]:
    """Load OAuth tokens from Google Secret Manager"""
    # Loads from:
    # - etrade-oauth-prod (for production)
    # - etrade-oauth-sandbox (for sandbox)
```

### **Token Usage**

**Trading System**:
- Loads tokens from Secret Manager at startup
- Automatically refreshes if tokens are renewed
- Uses tokens for all E*TRADE API calls
- Handles token expiration gracefully

**OAuth Backend**:
- Stores renewed tokens in Secret Manager
- Sends Telegram alerts on renewal
- Provides web interface for token management

---

## 🔔 Alert System

### **OAuth Alerts**

**Alert Types**:
- **OAuth Production Token Renewed**: When production token renewed
- **OAuth Sandbox Token Renewed**: When sandbox token renewed
- **OAuth Tokens Expired**: At midnight ET (consolidated alert)
- **OAuth Morning Alert**: Token status check at 5:30 AM PT

**Alert Delivery**:
- **Direct Telegram API**: Works 24/7, independent of trading system
- **Portal Agnostic**: Alert matches token renewed, not portal URL
- **Guaranteed Delivery**: Secret Manager credentials configured

---

## 🎯 System Validation & Performance

### **Current System Status (Rev 00231 - Jan 6, 2026)**

**OAuth System**: ✅ PRODUCTION ACTIVE  
**Trading System**: ✅ Rev 00231 deployed  
**Symbol System**: Dynamic (currently 145, fully scalable - Rev 00058)  
**SO Window**: 7:15-7:30 AM PT (15 minutes)  
**Execution**: 7:30 AM PT  
**Market Hours**: ET timezone-aware (Rev 00056)  
**Capital Deployment**: 88-90% (Rev 00090 - post-rounding redistribution)  
**Configuration**: Unified (65+ configurable settings - Rev 00201)  
**Trade Persistence**: GCS persistence working (Rev 00203)  

### **Production Readiness Status**
- **Token Management**: Google Secret Manager integration complete ✅
- **Firebase Frontend**: Daily token renewal interface operational ✅
- **System Integration**: All modules validated and working ✅
- **Performance Metrics**: Consistent high performance ✅
- **Risk Controls**: Proven effective across diverse trading scenarios ✅

---

## 📞 Contact Information

### **E*TRADE Support**
- **Developer Portal**: https://developer.etrade.com/
- **API Support**: api-support@etrade.com
- **Emergency Line**: 1-800-ETRADE-1

---

## 🎉 Bottom Line

The Easy ORB Strategy OAuth system provides:

✅ **Secure token management** with Google Secret Manager  
✅ **Daily renewal interface** via Firebase web app  
✅ **24/7 alert system** via Telegram  
✅ **Mobile-friendly** renewal process  
✅ **Anti-phishing security** architecture  
✅ **Automated keepalive** system  
✅ **Production ready** deployment  
✅ **Cost optimized** (~$11/month total)  

**Ready for 24/7 automated trading with secure OAuth token management!** 🔐

---

*Last Updated: January 6, 2026*  
*Version: Rev 00231 (Trade ID Shortening & Alert Formatting Improvements)*  
*For Google Cloud deployment details, see [docs/Cloud.md](Cloud.md)*  
*For trading strategy details, see [docs/Strategy.md](Strategy.md)*  
*For Firebase web app deployment, see [docs/Firebase.md](Firebase.md)*  
*For system configuration, see [docs/Settings.md](Settings.md)*
