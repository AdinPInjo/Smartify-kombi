#!/bin/bash
cd /Users/adinpinjo/repos/Smartify-kombi
python3 -m py_compile smartify/app.py && echo "✓ Compilation successful" || echo "✗ Compilation failed"

