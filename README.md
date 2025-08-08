# US Number Order Automation System

A comprehensive automation system for ordering virtual phone numbers in the US and Canada, with integrated MCP (Model Context Protocol) support for inventory management.

## 🏗️ System Architecture

### Core Components

1. **Main Processing Engine** (`main.py`)
   - Handles user requests via OpenAI Assistant
   - Searches multiple number providers (Plivo → Inteliquent)
   - Manages order placement and backorder requests
   - Integrates with MCP for inventory management

2. **Zendesk Integration** (`zendesk_webhook.py`)
   - Webhook endpoint for Zendesk ticket processing
   - Automatic ticket updates and status tracking
   - Customer communication management

3. **MCP Integration** (`mcp_integration.py`)
   - Adds ordered numbers to inventory via MCP server
   - Handles number metadata and carrier information
   - Manages authentication and API communication

4. **Backorder Tracking** (`backorder_tracker.py`)
   - Background monitoring of Inteliquent backorders
   - Automatic completion detection and processing
   - Database persistence for order tracking

5. **Startup Service** (`startup.py`)
   - Initializes all background services
   - Graceful shutdown handling
   - System monitoring and health checks

## 🔄 Workflow Overview

### 1. Request Processing
```
User Request → OpenAI Assistant → Number Requirements → Provider Search
```

### 2. Number Search Strategy
```
Plivo (Primary) → Inteliquent (Fallback) → Backorder (If needed)
```

### 3. Order Processing
```
Order Placed → MCP Inventory Addition → Zendesk Update → Customer Notification
```

### 4. Backorder Monitoring
```
Backorder Placed → Background Tracking → Completion Detection → MCP Addition
```

## 🚀 MCP Integration

### Purpose
The MCP (Model Context Protocol) integration automatically adds ordered numbers to your inventory system once they're successfully ordered from Inteliquent.

### Configuration
```python
# MCP Server Configuration
MCP_BASE_URL = "https://plivo-guruji-mcp-messaging.eks-bqbtjv.prod.plivops.com"
MCP_USERNAME = "n8n"
MCP_PASSWORD = "cGFzcw=="  # Base64 encoded "pass"
```

### Features
- **Automatic Inventory Addition**: Numbers are added to inventory immediately after Inteliquent orders
- **Metadata Preservation**: Maintains carrier, region, and service information
- **Error Handling**: Robust error handling with retry mechanisms
- **Logging**: Comprehensive logging for audit trails

### API Endpoint
```
POST /query
Content-Type: application/json
Authorization: Basic bjhuOnBhc3M=

{
    "query": "add numbers to inventory",
    "raw_args": {
        "numbers": [
            {
                "number": "+1234567890",
                "number_type": "LOCAL",
                "voice_enabled": true,
                "sms_enabled": true,
                "mms_enabled": true,
                "carrier_id": "inteliquent",
                "carrier_tier_id": 1,
                "region_id": 123,
                "city": "New York",
                "rate_center": "NYNYNYCL",
                "lata": "132",
                "account_id": 12345,
                "sub_account_id": 67890,
                "app_id": "app_123456",
                "country_iso2": "US",
                "skip_validation": false
            }
        ],
        "user_email": "admin@example.com",
        "skip_number_testing": true,
        "skip_phone_number_profile_restrictions": false,
        "reason_skip_number_testing": "Automated addition from Inteliquent order"
    }
}
```

## 📊 Backorder Tracking System

### Features
- **Background Monitoring**: Continuously tracks pending backorders
- **Automatic Detection**: Detects when backorders are completed
- **MCP Integration**: Automatically adds completed numbers to inventory
- **Zendesk Updates**: Updates tickets with completion status
- **Database Persistence**: SQLite database for order tracking

### Tracking Process
1. **Backorder Placement**: When a backorder is placed, it's added to tracking
2. **Background Polling**: System polls Inteliquent API every 4 hours
3. **Completion Detection**: Detects when orders are completed
4. **Inventory Addition**: Automatically adds completed numbers via MCP
5. **Customer Notification**: Updates Zendesk tickets with completion status

## 🛠️ Setup and Installation

### Environment Variables
```bash
# OpenAI Configuration
OPENAI_API_KEY=your_openai_api_key
OPENAI_PROJECT_ID=your_project_id
OPENAI_ASSISTANT_ID=your_assistant_id

# Plivo Configuration
PLIVO_AUTH_ID=your_plivo_auth_id
PLIVO_AUTH_TOKEN=your_plivo_auth_token

# Inteliquent Configuration
IQ_PRIVATE_KEY=your_inteliquent_private_key
IQ_SECRET_KEY=your_inteliquent_secret_key
IQ_TRUNK_GROUP=your_trunk_group

# Zendesk Configuration
ZENDESK_SUBDOMAIN=your_subdomain
ZENDESK_EMAIL=your_email
ZENDESK_TOKEN=your_token

# Redis Configuration (optional)
REDIS_HOST=localhost
REDIS_PORT=6379
```

### Installation
```bash
# Install dependencies
pip install -r requirements.txt

# Start the system
python startup.py
```

## 📁 File Structure

```
us-number-order/
├── main.py                 # Main processing engine
├── main_2.py              # Alternative main file
├── zendesk_webhook.py     # Zendesk integration
├── mcp_integration.py     # MCP server integration
├── backorder_tracker.py   # Backorder monitoring
├── startup.py             # System startup script
├── requirements.txt       # Python dependencies
├── Dockerfile            # Container configuration
├── fly.toml             # Fly.io deployment config
├── Inteliquent_API.yaml # Inteliquent API specification
└── README.md            # This file
```

## 🔧 API Endpoints

### Inteliquent API
- **Search Inventory**: `POST /tnInventory`
- **Order Numbers**: `POST /tnOrder`
- **Place Backorder**: `POST /tnRequest`
- **Check Status**: `POST /orderStatus` (placeholder)

### MCP Server
- **Add to Inventory**: `POST /query` with "add numbers to inventory"

### Zendesk Webhook
- **Ticket Processing**: `POST /zendesk-webhook`

## 📈 Monitoring and Logging

### Log Files
- `/data/us_ca_lc.log` - Main application logs
- `/data/startup.log` - Startup service logs
- `/data/backorders.db` - Backorder tracking database

### Key Metrics
- Number of orders processed
- Success/failure rates
- Backorder completion times
- MCP integration success rates

## 🚨 Error Handling

### MCP Integration Errors
- Network connectivity issues
- Authentication failures
- Invalid number formats
- Server timeouts

### Backorder Tracking Errors
- Inteliquent API failures
- Database connection issues
- Zendesk update failures

### Recovery Mechanisms
- Automatic retries with exponential backoff
- Graceful degradation
- Comprehensive error logging
- Alert notifications

## 🔄 Deployment

### Docker Deployment
```bash
# Build the container
docker build -t us-number-order .

# Run the container
docker run -d \
  --name us-number-order \
  -v /data:/data \
  --env-file .env \
  us-number-order
```

### Fly.io Deployment
```bash
# Deploy to Fly.io
fly deploy
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## 📄 License

This project is proprietary and confidential.

## 🆘 Support

For support and questions:
- Check the logs in `/data/`
- Review the Inteliquent API documentation
- Contact the development team

---

**Note**: This system integrates with multiple external APIs and services. Ensure all credentials and endpoints are properly configured before deployment.
