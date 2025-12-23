#!/bin/bash
# Quick test script to verify backend APIs on Raspberry Pi

echo "Testing /api/temperature/latest:"
curl -s "http://localhost:8000/api/temperature/latest" | python3 -m json.tool || echo "FAILED"

echo -e "\nTesting /api/gps/current:"
curl -s "http://localhost:8000/api/gps/current" | python3 -m json.tool || echo "FAILED"

echo -e "\nTesting /api/me (should show auth status):"
curl -s "http://localhost:8000/api/me" | python3 -m json.tool || echo "FAILED"

