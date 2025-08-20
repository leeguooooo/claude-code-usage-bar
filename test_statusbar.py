#!/usr/bin/env python3
"""
Test script to verify statusbar.py works correctly after translation
"""

import subprocess
import sys

def test_statusbar():
    """Test the statusbar script"""
    print("Testing statusbar.py...")
    
    try:
        result = subprocess.run(
            [sys.executable, 'statusbar.py'],
            capture_output=True,
            text=True,
            timeout=10,
            cwd='/Users/leo/github.com/claude-statusbar-monitor'
        )
        
        print(f"Return code: {result.returncode}")
        print(f"Output: {result.stdout}")
        
        if result.stderr:
            print(f"Errors: {result.stderr}")
        
        if result.returncode == 0:
            print("✅ Test passed - statusbar.py executed successfully")
            return True
        else:
            print("❌ Test failed - statusbar.py returned non-zero exit code")
            return False
            
    except subprocess.TimeoutExpired:
        print("⏰ Test timed out")
        return False
    except Exception as e:
        print(f"❌ Test error: {e}")
        return False

if __name__ == '__main__':
    success = test_statusbar()
    sys.exit(0 if success else 1)