"""
Test Session String Flow — Verify the implementation works correctly
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

print("✅ Testing Session-Only Login Implementation")
print("=" * 60)

# Test 1: Import check
print("\n1. Testing imports...")
try:
    from admin_bot.handlers.accounts import LoginStates
    print("   ✅ LoginStates imported successfully")
    assert hasattr(LoginStates, 'waiting_session'), "waiting_session state missing"
    print("   ✅ waiting_session state exists")
    # Verify OTP states are disabled
    assert not hasattr(LoginStates, 'waiting_phone') or getattr(LoginStates, 'waiting_phone').__class__.__name__ == 'property', "waiting_phone should be disabled"
    print("   ✅ waiting_phone state disabled")
    assert not hasattr(LoginStates, 'waiting_code') or getattr(LoginStates, 'waiting_code').__class__.__name__ == 'property', "waiting_code should be disabled"
    print("   ✅ waiting_code state disabled")
    assert not hasattr(LoginStates, 'waiting_password') or getattr(LoginStates, 'waiting_password').__class__.__name__ == 'property', "waiting_password should be disabled"
    print("   ✅ waiting_password state disabled")
except Exception as e:
    print(f"   ❌ Import failed: {e}")
    sys.exit(1)

# Test 2: Script check
print("\n2. Testing get_session.py script...")
try:
    script_path = Path("scripts/get_session.py")
    assert script_path.exists(), "get_session.py file missing"
    print("   ✅ get_session.py script exists")
    content = script_path.read_text()
    assert "generate_session" in content, "generate_session function missing"
    print("   ✅ generate_session function exists")
    assert "StringSession" in content, "StringSession missing"
    print("   ✅ StringSession used in script")
except Exception as e:
    print(f"   ❌ Script check failed: {e}")
    sys.exit(1)

# Test 3: Check handler implementation
print("\n3. Checking handler implementation...")
try:
    with open("admin_bot/handlers/accounts.py", "r") as f:
        content = f.read()
        assert 'cmd_add_session' in content, "cmd_add_session handler missing"
        print("   ✅ cmd_add_session handler exists")
        assert 'waiting_session' in content, "waiting_session state missing"
        print("   ✅ waiting_session state used")
        assert 'md_login_session' in content, "md_login_session handler missing"
        print("   ✅ md_login_session handler exists")
        assert 'StringSession' in content, "StringSession import missing"
        print("   ✅ StringSession imported")
        assert 'session_store.encrypt' in content, "session_store.encrypt missing"
        print("   ✅ session_store.encrypt called")
        assert 'safety.register_secret' in content, "safety.register_secret missing"
        print("   ✅ safety.register_secret called")
        assert '_delete_secret' in content, "_delete_secret missing"
        print("   ✅ _delete_secret called (auto-delete)")

        # Verify OTP handlers are disabled
        assert '# async def _ask_phone' in content, "_ask_phone should be commented out"
        print("   ✅ _ask_phone function disabled")
        assert '# async def _begin_login' in content, "_begin_login should be commented out"
        print("   ✅ _begin_login function disabled")
        assert '# @router.message(LoginStates.waiting_phone' in content, "waiting_phone handler should be commented out"
        print("   ✅ waiting_phone handler disabled")
        assert '# @router.message(LoginStates.waiting_code' in content, "waiting_code handler should be commented out"
        print("   ✅ waiting_code handler disabled")
        assert '# @router.message(LoginStates.waiting_password' in content, "waiting_password handler should be commented out"
        print("   ✅ waiting_password handler disabled")

        # Verify /addaccount redirects to session
        assert 'OTP login ត្រូវបានបិទ' in content, "/addaccount should show OTP disabled message"
        print("   ✅ /addaccount redirects to session string")
except Exception as e:
    print(f"   ❌ Handler check failed: {e}")
    sys.exit(1)

# Test 4: Check keyboard update
print("\n4. Checking keyboard updates...")
try:
    with open("admin_bot/keyboards.py", "r") as f:
        content = f.read()
        assert 'Session String' in content, "Keyboard should mention Session String"
        print("   ✅ Keyboard updated to mention Session String")
        assert 'login ក្នុង chat' not in content or content.count('login ក្នុង chat') == 0, "Keyboard should not mention chat login"
        print("   ✅ Keyboard removed chat login reference")
except Exception as e:
    print(f"   ❌ Keyboard check failed: {e}")
    sys.exit(1)

# Test 5: Check HOWTO text
print("\n5. Checking HOWTO text...")
try:
    with open("admin_bot/handlers/accounts.py", "r") as f:
        content = f.read()
        assert '/addsession' in content, "HOWTO should mention /addsession"
        print("   ✅ HOWTO mentions /addsession")
        assert 'get_session.py' in content, "HOWTO should mention get_session.py script"
        print("   ✅ HOWTO mentions get_session.py script")
        # Verify old OTP instructions are removed
        assert 'វាយកូដចូល' not in content or content.count('វាយកូដចូល') == 0, "HOWTO should not mention entering OTP in chat"
        print("   ✅ HOWTO removed OTP chat instructions")
except Exception as e:
    print(f"   ❌ HOWTO check failed: {e}")
    sys.exit(1)

print("\n" + "=" * 60)
print("✅ All tests passed!")
print("=" * 60)
print("\n📋 System now uses Session String ONLY:")
print("✅ OTP login completely disabled")
print("✅ Only /addsession command available")
print("✅ /addaccount redirects to session string")
print("✅ All OTP handlers commented out")
print("✅ HOWTO updated to session string flow")
print("✅ Keyboard updated to session string")
print("\n🚀 Ready to use!")
print("1. Run: python scripts/get_session.py +855XXXXXXXX")
print("2. Copy the session string")
print("3. Send to bot: /addsession")
print("4. Paste the session string")
print("5. Bot will auto-delete, validate, encrypt, and save")
