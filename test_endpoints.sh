#!/bin/bash

# Test script for Sage SQL endpoints after fixes
# Set your API URL and token below

API_URL="https://sodigazback.yingr-ai.com/api"
TOKEN="your_auth_token_here"  # Replace with actual token

echo "================================"
echo "Testing Fixed Sage SQL Endpoints"
echo "================================"
echo ""

# Test 1: Check Sage SQL Health
echo "[1] Testing GET /admin/integration/sage-sql-health"
echo "============================================"
curl -s -X GET "$API_URL/admin/integration/sage-sql-health" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" | python3 -m json.tool

echo ""
echo ""

# Test 2: Sync Sage Drivers (Driver Code Reading)
echo "[2] Testing GET /admin/sync-sage-drivers"
echo "============================================"
curl -s -X GET "$API_URL/admin/sync-sage-drivers" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" | python3 -m json.tool

echo ""
echo ""

# Test 3: Auto-create Driver Mappings
echo "[3] Testing GET /admin/auto-create-driver-mappings"
echo "===================================================="
curl -s -X GET "$API_URL/admin/auto-create-driver-mappings" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" | python3 -m json.tool

echo ""
echo ""
echo "================================"
echo "Tests Complete"
echo "================================"
