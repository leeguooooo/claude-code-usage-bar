#!/usr/bin/env python3
"""
Claude Code Status Bar Setup Script
Automatically configure Claude Code status bar display
"""

import json
import os
import stat
from pathlib import Path

def get_claude_settings_path() -> Path:
    """Get Claude settings file path"""
    return Path.home() / '.claude' / 'settings.json'

def get_statusbar_script_path() -> Path:
    """Get status bar script path"""
    return Path(__file__).parent / 'statusbar.py'

def make_script_executable():
    """Make status bar script executable"""
    script_path = get_statusbar_script_path()
    current_permissions = script_path.stat().st_mode
    script_path.chmod(current_permissions | stat.S_IEXEC)
    print(f"✅ Made {script_path} executable")

def backup_existing_settings(settings_path: Path) -> bool:
    """Backup existing settings file"""
    if settings_path.exists():
        backup_path = settings_path.with_suffix('.json.backup')
        backup_path.write_text(settings_path.read_text())
        print(f"✅ Backed up existing settings to {backup_path}")
        return True
    return False

def update_claude_settings():
    """Update Claude settings file"""
    settings_path = get_claude_settings_path()
    script_path = get_statusbar_script_path()
    
    # Ensure .claude directory exists
    settings_path.parent.mkdir(exist_ok=True)
    
    # Backup existing settings
    backup_existing_settings(settings_path)
    
    # Read existing settings or create new ones
    settings = {}
    if settings_path.exists():
        try:
            with open(settings_path, 'r', encoding='utf-8') as f:
                settings = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            settings = {}
    
    # Add status bar configuration
    settings['statusLine'] = {
        'type': 'command',
        'command': str(script_path.absolute()),
        'padding': 0
    }
    
    # Write settings file
    with open(settings_path, 'w', encoding='utf-8') as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
    
    print(f"✅ Updated Claude settings: {settings_path}")

def test_statusbar_script():
    """Test status bar script"""
    script_path = get_statusbar_script_path()
    
    print("\n🧪 Testing statusbar script...")
    
    # Simulate running the script
    import subprocess
    try:
        result = subprocess.run(
            ['python3', str(script_path)],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            print(f"✅ Script test successful")
            print(f"📊 Output: {result.stdout.strip()}")
        else:
            print(f"❌ Script test failed")
            print(f"Error: {result.stderr}")
    except subprocess.TimeoutExpired:
        print("⏰ Script test timed out")
    except Exception as e:
        print(f"❌ Script test error: {e}")

def main():
    """Main function"""
    print("🔧 Claude Code Status Bar Setup Tool\n")
    
    try:
        # 1. Make script executable
        make_script_executable()
        
        # 2. Update Claude settings
        update_claude_settings()
        
        # 3. Test script
        test_statusbar_script()
        
        print("\n🎉 Setup complete!")
        print("\n📝 Next steps:")
        print("1. Restart Claude Code")
        print("2. The status bar will display your token usage")
        print("3. For manual configuration, run: /statusline")
        
        print("\n🎨 Status bar format example:")
        print("🔋 45.2k/88k | $12.30/$35 | MAX5 ⚡")
        
    except Exception as e:
        print(f"❌ Setup failed: {e}")
        print("\n🔧 Manual setup steps:")
        print("1. Edit ~/.claude/settings.json")
        print("2. Add the following configuration:")
        print(json.dumps({
            "statusLine": {
                "type": "command", 
                "command": str(get_statusbar_script_path().absolute()),
                "padding": 0
            }
        }, indent=2))

if __name__ == '__main__':
    main()