import requests
import sys
import json
import base64
from datetime import datetime
from pathlib import Path
import io
from PIL import Image

class DAOCitizenshipAPITester:
    def __init__(self, base_url="https://identity-verify-22.preview.emergentagent.com"):
        self.base_url = base_url
        self.api_url = f"{base_url}/api"
        self.tests_run = 0
        self.tests_passed = 0
        self.test_results = []

    def log_test(self, name, success, details=""):
        """Log test result"""
        self.tests_run += 1
        if success:
            self.tests_passed += 1
            print(f"✅ {name} - PASSED")
        else:
            print(f"❌ {name} - FAILED: {details}")
        
        self.test_results.append({
            'name': name,
            'success': success,
            'details': details
        })

    def run_test(self, name, method, endpoint, expected_status, data=None, files=None):
        """Run a single API test"""
        url = f"{self.api_url}/{endpoint}"
        headers = {'Content-Type': 'application/json'} if not files else {}

        print(f"\n🔍 Testing {name}...")
        print(f"   URL: {url}")
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=headers, timeout=30)
            elif method == 'POST':
                if files:
                    response = requests.post(url, files=files, timeout=30)
                else:
                    response = requests.post(url, json=data, headers=headers, timeout=30)

            success = response.status_code == expected_status
            
            if success:
                try:
                    response_data = response.json()
                    print(f"   Status: {response.status_code}")
                    print(f"   Response: {json.dumps(response_data, indent=2)}")
                    self.log_test(name, True)
                    return True, response_data
                except:
                    print(f"   Status: {response.status_code}")
                    print(f"   Response: {response.text}")
                    self.log_test(name, True)
                    return True, {}
            else:
                error_msg = f"Expected {expected_status}, got {response.status_code}"
                try:
                    error_data = response.json()
                    error_msg += f" - {error_data}"
                except:
                    error_msg += f" - {response.text}"
                
                print(f"   Status: {response.status_code}")
                print(f"   Error: {error_msg}")
                self.log_test(name, False, error_msg)
                return False, {}

        except Exception as e:
            error_msg = f"Connection error: {str(e)}"
            print(f"   Error: {error_msg}")
            self.log_test(name, False, error_msg)
            return False, {}

    def test_root_endpoint(self):
        """Test the root API endpoint"""
        return self.run_test("Root API Endpoint", "GET", "", 200)

    def test_clave_unica_valid(self):
        """Test ClaveÚnica with valid RUT"""
        return self.run_test(
            "ClaveÚnica - Valid RUT",
            "POST",
            "auth/clave-unica",
            200,
            data={"rut": "12345678-9"}
        )

    def test_clave_unica_invalid(self):
        """Test ClaveÚnica with invalid RUT"""
        success, response = self.run_test(
            "ClaveÚnica - Invalid RUT",
            "POST",
            "auth/clave-unica",
            200,
            data={"rut": "123"}
        )
        
        # Check if the response indicates failure
        if success and response.get('ok') == False:
            print("   ✓ Correctly rejected invalid RUT")
            return True, response
        elif success and response.get('ok') == True:
            self.log_test("ClaveÚnica - Invalid RUT", False, "Should have rejected invalid RUT")
            return False, response
        
        return success, response

    def test_nfc_authentication(self):
        """Test NFC authentication"""
        return self.run_test("NFC Authentication", "POST", "auth/nfc", 200)

    def create_test_image(self):
        """Create a simple test image for liveness detection"""
        # Create a simple 100x100 RGB image
        img = Image.new('RGB', (100, 100), color='red')
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='JPEG')
        img_bytes.seek(0)
        return img_bytes

    def test_liveness_detection(self):
        """Test liveness detection with real AI"""
        print(f"\n🔍 Testing Liveness Detection (Real AI)...")
        print("   Creating test image...")
        
        try:
            # Create test image
            test_image = self.create_test_image()
            
            files = {
                'file': ('test_selfie.jpg', test_image, 'image/jpeg')
            }
            
            url = f"{self.api_url}/auth/liveness"
            print(f"   URL: {url}")
            
            response = requests.post(url, files=files, timeout=60)  # Longer timeout for AI
            
            success = response.status_code == 200
            
            if success:
                try:
                    response_data = response.json()
                    print(f"   Status: {response.status_code}")
                    print(f"   Response: {json.dumps(response_data, indent=2)}")
                    
                    # Check if AI analysis worked
                    if response_data.get('ok') and 'score' in response_data:
                        print(f"   ✓ AI Analysis completed with score: {response_data['score']}")
                        self.log_test("Liveness Detection (Real AI)", True)
                        return True, response_data
                    else:
                        error_msg = f"AI analysis failed: {response_data.get('error', 'Unknown error')}"
                        self.log_test("Liveness Detection (Real AI)", False, error_msg)
                        return False, response_data
                        
                except Exception as e:
                    error_msg = f"Failed to parse response: {str(e)}"
                    self.log_test("Liveness Detection (Real AI)", False, error_msg)
                    return False, {}
            else:
                error_msg = f"Expected 200, got {response.status_code} - {response.text}"
                print(f"   Error: {error_msg}")
                self.log_test("Liveness Detection (Real AI)", False, error_msg)
                return False, {}
                
        except Exception as e:
            error_msg = f"Connection error: {str(e)}"
            print(f"   Error: {error_msg}")
            self.log_test("Liveness Detection (Real AI)", False, error_msg)
            return False, {}

    def test_liveness_invalid_file(self):
        """Test liveness detection with invalid file"""
        print(f"\n🔍 Testing Liveness Detection - Invalid File...")
        
        try:
            # Create a text file instead of image
            files = {
                'file': ('test.txt', io.BytesIO(b'This is not an image'), 'text/plain')
            }
            
            url = f"{self.api_url}/auth/liveness"
            response = requests.post(url, files=files, timeout=30)
            
            success = response.status_code == 200
            
            if success:
                response_data = response.json()
                print(f"   Status: {response.status_code}")
                print(f"   Response: {json.dumps(response_data, indent=2)}")
                
                # Should return ok=False for invalid file
                if response_data.get('ok') == False:
                    print("   ✓ Correctly rejected invalid file")
                    self.log_test("Liveness Detection - Invalid File", True)
                    return True, response_data
                else:
                    self.log_test("Liveness Detection - Invalid File", False, "Should have rejected invalid file")
                    return False, response_data
            else:
                error_msg = f"Expected 200, got {response.status_code}"
                self.log_test("Liveness Detection - Invalid File", False, error_msg)
                return False, {}
                
        except Exception as e:
            error_msg = f"Connection error: {str(e)}"
            self.log_test("Liveness Detection - Invalid File", False, error_msg)
            return False, {}

    def test_wallet_connect(self):
        """Test wallet connection"""
        return self.run_test("Wallet Connection", "POST", "wallet/connect", 200)

    def test_mint_sbt(self):
        """Test SBT minting"""
        return self.run_test(
            "SBT Minting",
            "POST",
            "membership/mint",
            200,
            data={
                "wallet_address": "0x1234567890ABCDEF",
                "assurance_level": "AL2",
                "doc_hash": "0xDOCHASH123"
            }
        )

    def test_dashboard_stats(self):
        """Test dashboard statistics"""
        return self.run_test("Dashboard Statistics", "GET", "dashboard/stats", 200)

    def test_status_endpoints(self):
        """Test status check endpoints"""
        # Test creating status check
        success1, response1 = self.run_test(
            "Create Status Check",
            "POST",
            "status",
            200,
            data={"client_name": "test_client"}
        )
        
        # Test getting status checks
        success2, response2 = self.run_test("Get Status Checks", "GET", "status", 200)
        
        return success1 and success2

    def run_all_tests(self):
        """Run all API tests"""
        print("🚀 Starting DAO Citizenship API Tests")
        print(f"Base URL: {self.base_url}")
        print("=" * 60)

        # Test all endpoints
        self.test_root_endpoint()
        self.test_status_endpoints()
        self.test_clave_unica_valid()
        self.test_clave_unica_invalid()
        self.test_nfc_authentication()
        self.test_liveness_detection()  # Real AI test
        self.test_liveness_invalid_file()
        self.test_wallet_connect()
        self.test_mint_sbt()
        self.test_dashboard_stats()

        # Print summary
        print("\n" + "=" * 60)
        print("📊 TEST SUMMARY")
        print("=" * 60)
        print(f"Tests run: {self.tests_run}")
        print(f"Tests passed: {self.tests_passed}")
        print(f"Tests failed: {self.tests_run - self.tests_passed}")
        print(f"Success rate: {(self.tests_passed/self.tests_run)*100:.1f}%")

        # Print failed tests
        failed_tests = [t for t in self.test_results if not t['success']]
        if failed_tests:
            print("\n❌ FAILED TESTS:")
            for test in failed_tests:
                print(f"  - {test['name']}: {test['details']}")
        else:
            print("\n🎉 ALL TESTS PASSED!")

        return self.tests_passed == self.tests_run

def main():
    tester = DAOCitizenshipAPITester()
    success = tester.run_all_tests()
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())