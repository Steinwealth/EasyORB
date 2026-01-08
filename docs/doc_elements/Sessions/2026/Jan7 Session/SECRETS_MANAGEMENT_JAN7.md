# Secrets Management Guide
## Easy ORB Strategy - Secure Credential Management

**Last Updated**: January 7, 2026  
**Version**: Rev 00233  
**Status**: ✅ **IMPLEMENTED**

---

## 🎯 **Overview**

The Easy ORB Strategy uses a **two-tier secrets management system**:

1. **Production/Deployment**: Google Secret Manager (GCP)
2. **Local Development**: `secretsprivate/` folder (gitignored)

**All sensitive credentials are stored securely and never committed to Git.**

---

## 📋 **Secrets Storage Locations**

### **1. Production/Deployment** ☁️

**Location**: Google Secret Manager  
**Access**: Via service account with Secret Manager permissions  
**Used By**: Cloud Run services, production deployments

**Secret Names**:
- `etrade/sandbox/consumer_key`
- `etrade/sandbox/consumer_secret`
- `etrade/prod/consumer_key`
- `etrade/prod/consumer_secret`
- `telegram/bot_token`
- `telegram/chat_id`
- `EtradeStrategy` (combined OAuth tokens)

### **2. Local Development** 💻

**Location**: `secretsprivate/` folder  
**Access**: Local file system (gitignored)  
**Used By**: Local development, testing

**Files**:
- `secretsprivate/etrade.env` - E*TRADE credentials
- `secretsprivate/telegram.env` - Telegram credentials

**⚠️ CRITICAL**: This folder is **gitignored** and will **never** be committed to Git.

---

## 🔧 **Setup Instructions**

### **For Local Development**

1. **Create secrets files**:
   ```bash
   cd "0. Strategies and Automations/1. The Easy ORB Strategy"
   
   # Copy templates
   cp secretsprivate/etrade.env.template secretsprivate/etrade.env
   cp secretsprivate/telegram.env.template secretsprivate/telegram.env
   ```

2. **Fill in your credentials**:
   - Edit `secretsprivate/etrade.env` with your E*TRADE keys/secrets
   - Edit `secretsprivate/telegram.env` with your Telegram bot token/chat ID

3. **Verify gitignore**:
   ```bash
   git check-ignore secretsprivate/etrade.env
   # Should output: secretsprivate/etrade.env
   ```

4. **Test loading**:
   ```bash
   python3 -c "from modules.config_loader import ConfigLoader; c = ConfigLoader(); print('✅ Secrets loaded')"
   ```

### **For Production/Deployment**

1. **Store secrets in Google Secret Manager**:
   ```bash
   # E*TRADE Sandbox
   echo -n "your_sandbox_key" | gcloud secrets create etrade/sandbox/consumer_key --data-file=-
   echo -n "your_sandbox_secret" | gcloud secrets create etrade/sandbox/consumer_secret --data-file=-
   
   # E*TRADE Production
   echo -n "your_prod_key" | gcloud secrets create etrade/prod/consumer_key --data-file=-
   echo -n "your_prod_secret" | gcloud secrets create etrade/prod/consumer_secret --data-file=-
   
   # Telegram
   echo -n "your_bot_token" | gcloud secrets create telegram/bot_token --data-file=-
   echo -n "your_chat_id" | gcloud secrets create telegram/chat_id --data-file=-
   ```

2. **Verify service account permissions**:
   ```bash
   gcloud projects get-iam-policy easy-etrade-strategy \
     --flatten="bindings[].members" \
     --filter="bindings.members:serviceAccount:*"
   ```

3. **Deploy**: Secrets are automatically loaded from Secret Manager in production.

---

## 🔄 **Migration from Config Files**

If you have hardcoded secrets in config files:

1. **Run migration script**:
   ```bash
   python3 scripts/migrate_secrets_to_private.py
   ```

2. **Review migrated secrets**:
   ```bash
   # Check what was migrated
   cat secretsprivate/etrade.env
   cat secretsprivate/telegram.env
   ```

3. **Remove hardcoded values from config files**:
   - Keep template files (`.env.template`)
   - Remove actual secrets from `.env` files
   - Or delete `.env` files entirely (use templates)

4. **Verify gitignore**:
   ```bash
   git status
   # secretsprivate/ should not appear
   ```

---

## 📁 **File Structure**

```
secretsprivate/
├── README.md                    # Documentation
├── .gitkeep                     # Ensures folder is tracked
├── etrade.env.template          # Template (safe to commit)
├── telegram.env.template        # Template (safe to commit)
├── etrade.env                   # Actual secrets (gitignored)
└── telegram.env                 # Actual secrets (gitignored)
```

---

## 🔒 **Security Best Practices**

### **✅ DO:**

- ✅ Store production secrets in Google Secret Manager
- ✅ Use `secretsprivate/` for local development only
- ✅ Keep template files (`.template`) in Git
- ✅ Rotate credentials if exposed
- ✅ Use strong, unique credentials
- ✅ Limit Secret Manager access to service accounts only

### **❌ DON'T:**

- ❌ Commit `secretsprivate/` folder to Git
- ❌ Hardcode secrets in config files
- ❌ Share secrets via email/chat
- ❌ Store secrets in public repositories
- ❌ Use production secrets in development
- ❌ Log secrets in application logs

---

## 🔍 **How It Works**

### **Configuration Loading Priority**

The `config_loader.py` module loads secrets in this order:

1. **Google Secret Manager** (production only)
   - Used when `ENVIRONMENT=production`
   - Accessed via service account

2. **`secretsprivate/` folder** (local development)
   - Used when `ENVIRONMENT=development` or `sandbox`
   - Loads from `etrade.env` and `telegram.env`

3. **Environment Variables** (fallback)
   - Used if Secret Manager or `secretsprivate/` unavailable
   - Set via `export` or `.env` files

### **Code Flow**

```python
# In config_loader.py
def _load_secrets(self):
    if environment == "production":
        # Use Google Secret Manager
        load_from_secret_manager()
    else:
        # Use secretsprivate/ folder
        load_from_secretsprivate()
```

---

## 📝 **Secret File Formats**

### **`secretsprivate/etrade.env`**

```bash
# E*TRADE Sandbox/Demo Credentials
ETRADE_SANDBOX_KEY=your_sandbox_key_here
ETRADE_SANDBOX_SECRET=your_sandbox_secret_here
ETRADE_DEMO_CONSUMER_KEY=your_demo_key_here
ETRADE_DEMO_CONSUMER_SECRET=your_demo_secret_here
ETRADE_DEMO_ACCOUNT_ID=your_account_id_here

# E*TRADE Production Credentials
ETRADE_PROD_KEY=your_prod_key_here
ETRADE_PROD_SECRET=your_prod_secret_here
ETRADE_PROD_ACCOUNT_ID=your_account_id_here
```

### **`secretsprivate/telegram.env`**

```bash
# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
```

---

## 🚨 **Troubleshooting**

### **Secrets Not Loading**

1. **Check file exists**:
   ```bash
   ls -la secretsprivate/etrade.env
   ls -la secretsprivate/telegram.env
   ```

2. **Check file permissions**:
   ```bash
   chmod 600 secretsprivate/*.env
   ```

3. **Check gitignore**:
   ```bash
   git check-ignore secretsprivate/etrade.env
   ```

4. **Check environment**:
   ```bash
   echo $ENVIRONMENT
   # Should be "development" or "sandbox" for local secrets
   ```

### **Production Secrets Not Loading**

1. **Check Secret Manager**:
   ```bash
   gcloud secrets list
   ```

2. **Check service account permissions**:
   ```bash
   gcloud projects get-iam-policy easy-etrade-strategy
   ```

3. **Check Cloud Run environment**:
   ```bash
   gcloud run services describe easy-etrade-strategy
   ```

---

## 📚 **Related Documentation**

- **[docs/doc_elements/Sessions/2026/Jan7 Session/SECURITY_AUDIT_JAN7.md](doc_elements/Sessions/2026/Jan7%20Session/SECURITY_AUDIT_JAN7.md)**: January 7, 2026 security audit (session-specific)
- **[docs/Cloud.md](Cloud.md)**: Cloud deployment and Secret Manager setup
- **[docs/OAuth.md](OAuth.md)**: OAuth token management
- **[secretsprivate/README.md](../secretsprivate/README.md)**: Local secrets folder documentation

---

## ✅ **Verification Checklist**

- [ ] `secretsprivate/` folder exists
- [ ] `secretsprivate/` is in `.gitignore`
- [ ] Template files exist (`.env.template`)
- [ ] Actual secret files exist (`.env`)
- [ ] Secrets load correctly in development
- [ ] Production secrets stored in Secret Manager
- [ ] Service account has Secret Manager permissions
- [ ] No hardcoded secrets in config files
- [ ] Template files are safe to commit

---

*Last Updated: January 7, 2026*  
*Version: Rev 00233*  
*Status: ✅ Secrets Management System Implemented*

