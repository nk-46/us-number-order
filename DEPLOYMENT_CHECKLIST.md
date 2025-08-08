# 🚀 DEPLOYMENT CHECKLIST - US Number Order System

## 📋 **PRE-DEPLOYMENT VERIFICATION**

### ✅ **Code Changes Summary**
- **Added Files**: `mcp_integration.py`, `backorder_tracker.py`, `startup.py`
- **Modified Files**: `main.py`, `zendesk_webhook.py`, `README.md`
- **Deleted Files**: `backup_main.py`, `main_2.py`, `parse_and_search_2.py`, `debug_region_lookup.py`, `region-id/` directory
- **New Dependencies**: All required dependencies already in `requirements.txt`

### ✅ **Critical Fixes Applied**
- ✅ Fixed `main.py` to use new `get_region_id_from_area_code()` function
- ✅ Removed complex CSV lookup logic
- ✅ Implemented simple region_id logic (101 for US, 102 for Canada)
- ✅ Added MCP integration for inventory management
- ✅ Added backorder tracking system
- ✅ Updated backorder age threshold to 6 hours (from 24 hours)

## 🔧 **ENVIRONMENT VARIABLES REQUIRED**

### **MCP Integration Variables**
```bash
MCP_URL=https://plivo-guruji-mcp-messaging.eks-bqbtjv.prod.plivops.com/query
MCP_USERNAME=n8n
MCP_PASSWORD=cGFzcw==
```

### **Inteliquent Variables** (Already Present)
```bash
IQ_PRIVATE_KEY=your_private_key
IQ_SECRET_KEY=your_secret_key
IQ_ACCESS_TOKEN=your_access_token
```

### **Existing Variables** (No Changes)
```bash
OPENAI_API_KEY=your_openai_key
PLIVO_AUTH_ID=your_plivo_auth_id
PLIVO_AUTH_TOKEN=your_plivo_auth_token
```

## 📁 **FILES TO BE DEPLOYED**

### **New Files** (Must be added to GitHub)
- ✅ `mcp_integration.py` - MCP client and region ID logic
- ✅ `backorder_tracker.py` - Background backorder tracking
- ✅ `startup.py` - System startup script
- ✅ `data/` directory - For logs and databases

### **Modified Files** (Will be updated)
- ✅ `main.py` - Enhanced with MCP integration
- ✅ `zendesk_webhook.py` - Updated for new functionality
- ✅ `README.md` - Updated documentation

### **Deleted Files** (Will be removed)
- ❌ `backup_main.py` - Backup file
- ❌ `main_2.py` - Old version
- ❌ `parse_and_search_2.py` - Old version
- ❌ `debug_region_lookup.py` - Old CSV debug script
- ❌ `region-id/` directory - CSV files (no longer needed)

## 🚨 **PRODUCTION SAFETY CHECKS**

### ✅ **Backward Compatibility**
- ✅ Existing Inteliquent API calls unchanged
- ✅ Existing Zendesk webhook functionality preserved
- ✅ Existing Plivo integration unchanged
- ✅ Existing OpenAI integration unchanged

### ✅ **Error Handling**
- ✅ MCP integration wrapped in try-catch blocks
- ✅ Backorder tracking has proper error handling
- ✅ Graceful degradation if MCP is unavailable

### ✅ **Logging**
- ✅ Comprehensive logging for all new functionality
- ✅ Error logging for debugging
- ✅ Success/failure tracking

## 🔄 **DEPLOYMENT STEPS**

### **Step 1: Commit Changes to GitHub**
```bash
git add .
git commit -m "Add MCP integration and backorder tracking"
git push origin main
```

### **Step 2: Verify GitHub Repository**
- ✅ All new files are present
- ✅ Modified files are updated
- ✅ Deleted files are removed
- ✅ No syntax errors

### **Step 3: Monitor Fly.io Deployment**
- ✅ Check `number-order-us` deployment
- ✅ Check `us-num-order-redis` deployment
- ✅ Verify environment variables are set
- ✅ Test webhook functionality

### **Step 4: Post-Deployment Verification**
- ✅ Test immediate inventory flow
- ✅ Test backorder creation
- ✅ Test MCP integration
- ✅ Verify logging is working

## 🧪 **TESTING SCENARIOS**

### **Test 1: Immediate Inventory**
```
User Request: "Could we please get 10 numbers with the 934 area code?"
Expected: Numbers ordered and added to inventory via MCP
```

### **Test 2: Backorder Creation**
```
User Request: "Could we please get 5 numbers with the 555 area code?"
Expected: Backorder created and tracked
```

### **Test 3: Backorder Completion**
```
Scenario: Backorder completes after 4 hours
Expected: Numbers automatically added to inventory via MCP
```

## 📊 **MONITORING**

### **Logs to Monitor**
- `/data/us_ca_lc.log` - Main application logs
- `/data/startup.log` - Startup service logs
- `data/backorders.db` - Backorder tracking database

### **Key Metrics**
- ✅ MCP integration success rate
- ✅ Backorder completion rate
- ✅ Number addition success rate
- ✅ Error rates and types

## 🚨 **ROLLBACK PLAN**

### **If Issues Occur**
1. **Immediate**: Disable MCP integration in environment variables
2. **Short-term**: Revert to previous GitHub commit
3. **Long-term**: Debug and fix issues

### **Rollback Commands**
```bash
# Revert to previous version
git revert HEAD
git push origin main

# Or disable MCP integration
# Set MCP_URL to empty string in Fly.io environment
```

## ✅ **FINAL CHECKLIST**

- [ ] All new files committed to GitHub
- [ ] All modified files committed to GitHub
- [ ] All deleted files removed from GitHub
- [ ] Environment variables configured in Fly.io
- [ ] Deployment successful
- [ ] Basic functionality tested
- [ ] Logs are being generated
- [ ] No critical errors in logs

## 📞 **CONTACT INFORMATION**

**For Issues**: Check logs first, then contact development team
**Emergency Rollback**: Use Fly.io dashboard or CLI commands
**Monitoring**: Check Fly.io logs and application logs

---

**⚠️ IMPORTANT**: This deployment adds significant new functionality. Monitor closely for the first 24 hours after deployment. 