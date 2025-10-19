import requests
import json
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore
from firebase_admin import exceptions as firebase_exceptions

# --- Cấu hình API Myfxbook ---
# ⚠️ THAY THẾ BẰNG THÔNG TIN THỰC TẾ CỦA BẠN
MY_EMAIL = "hai12b3@gmail.com"  
MY_PASSWORD = "Hadeshai5"        
LOGIN_API = f"https://www.myfxbook.com/api/login.json?email={MY_EMAIL}&password={MY_PASSWORD}"
GET_ACCOUNTS_API_BASE = "https://www.myfxbook.com/api/get-my-accounts.json"
GET_OPEN_TRADES_API_BASE = "https://www.myfxbook.com/api/get-open-trades.json"

# --- Cấu hình Firebase ---
SERVICE_ACCOUNT_FILE = 'datafx-45432-firebase-adminsdk-fbsvc-3132a63c50.json' 
COLLECTION_NAME = 'myfxbook_snapshots'      
OPEN_TRADES_SUMMARY_COLLECTION = 'myfxbook_trades_summary' 
SESSION_DOC_ID = 'current_session'          
TRADES_DOC_ID = 'current_trades_summary'     

def initialize_firebase():
    """Khởi tạo Firebase Admin SDK."""
    try:
        if not firebase_admin._apps:
            cred = credentials.Certificate(SERVICE_ACCOUNT_FILE)
            firebase_admin.initialize_app(cred)
        return firestore.client()
    except firebase_exceptions.FirebaseError as fe:
        print(f"❌ LỖI FIREBASE CỤ THỂ: Không thể khởi tạo. Vui lòng kiểm tra file khóa {SERVICE_ACCOUNT_FILE} và Secret: {fe}")
        raise
    except Exception as e:
        print(f"❌ LỖI KHỞI TẠO CHUNG: {e}")
        raise

def get_session_id():
    """Lấy Session ID bằng cách đăng nhập."""
    print("⏳ Đang đăng nhập để lấy Session ID...")
    try:
        response = requests.get(LOGIN_API, timeout=30) 
        
        if response.status_code != 200:
            print(f"❌ Lỗi HTTP: Status Code {response.status_code}. Phản hồi của server: {response.text}")
            response.raise_for_status()
        
        data = response.json()
        
        # LOGIC KIỂM TRA THÀNH CÔNG ĐÃ ĐƯỢC SỬA 
        is_success = data.get('session') and (data.get('error') is False or data.get('error') is None)
        
        if is_success:
            session_id = data['session']
            print(f"✅ Đăng nhập thành công! Session ID: {session_id[:10]}...")
            return session_id
        else:
            print("❌ Đăng nhập thất bại. Mã phản hồi JSON (Kiểm tra Email/Password):")
            print(json.dumps(data, indent=4))
            return None
            
    except requests.exceptions.Timeout:
        print("❌ LỖI MẠNG: Đăng nhập bị Timeout (Quá 30 giây).")
        return None
    except requests.exceptions.RequestException as e:
        print(f"❌ LỖI KẾT NỐI API Myfxbook (Đăng nhập): {e}")
        return None
    except json.JSONDecodeError:
        print(f"❌ LỖI PHÂN TÍCH JSON: Phản hồi không phải JSON hợp lệ. Nội dung: {response.text[:100]}...")
        return None


def fetch_data(api_url, session_id, **params): 
    """Lấy dữ liệu từ API Myfxbook."""
    full_url = f"{api_url}?session={session_id}"
    
    if params:
        for key, value in params.items():
            full_url += f"&{key}={value}"

    try:
        response = requests.get(full_url, timeout=30)
        
        if response.status_code != 200:
            print(f"❌ Lỗi HTTP: Status Code {response.status_code} khi gọi {api_url}")
            response.raise_for_status()
            
        data = response.json()
        
        if data.get('error') is True:
            print(f"❌ API báo lỗi khi gọi {api_url}. JSON phản hồi:")
            print(json.dumps(data, indent=4))
            return None 
            
        return data 
        
    except requests.exceptions.Timeout:
        print(f"❌ LỖI MẠNG: Gọi API {api_url} bị Timeout.")
        return None
    except requests.exceptions.RequestException as e:
        print(f"❌ LỖI KẾT NỐI API Myfxbook ({api_url}): {e}")
        return None
    except json.JSONDecodeError:
        print(f"❌ LỖI PHÂN TÍCH JSON: Phản hồi không phải JSON hợp lệ từ {api_url}. Nội dung: {response.text[:100]}...")
        return None

def find_account_list(data):
    """
    Tìm mảng dữ liệu tài khoản (hoặc lệnh mở) trong phản hồi JSON thô một cách linh hoạt.
    Sẽ tìm kiếm bất kỳ trường nào là một list không rỗng chứa dictionary có key đặc trưng.
    """
    if not isinstance(data, dict):
        return []

    # Kiểm tra tổng quát hơn: tìm bất kỳ trường nào là một list không rỗng, 
    # và phần tử đầu tiên là một dict có các key đặc trưng của tài khoản.
    for key, value in data.items():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            # Các key đặc trưng của object tài khoản:
            # Dùng 3 key này để đảm bảo nó là mảng tài khoản, không phải mảng lệnh mở/lịch sử giao dịch.
            account_keys = {'id', 'name', 'balance', 'equity', 'gain'} 
            
            # Nếu tất cả các key đặc trưng đều có trong phần tử đầu tiên, đây là mảng tài khoản.
            if account_keys.issubset(value[0].keys()):
                 print(f"ℹ️ Đã tìm thấy danh sách tài khoản dưới key: '{key}'")
                 return value
                 
    # Nếu không tìm thấy, trả về list rỗng
    return []

def save_snapshot_to_firestore(db, data):
    """Lưu dữ liệu snapshot vào Firestore."""
    
    # 🆕 Sử dụng hàm tìm kiếm linh hoạt để lấy danh sách tài khoản
    accounts_list = find_account_list(data)
    
    if not accounts_list:
        print("❌ Lỗi: Không tìm thấy danh sách tài khoản hợp lệ trong phản hồi API.")
        return

    try:
        current_time = datetime.now()
        timestamp_str = current_time.isoformat()
        
        # 🟢 ĐÃ SỬA: Lưu mảng tài khoản vào trường 'accounts' theo yêu cầu
        document_data = {
            'timestamp': timestamp_str,
            'accounts': accounts_list, 
            'success': data.get('error') is False
        }
        
        # Lưu vào document dashboard (latest)
        doc_ref = db.collection(COLLECTION_NAME).document(SESSION_DOC_ID)
        doc_ref.set(document_data)
        
        # Lưu vào history
        history_doc_id = current_time.strftime("%Y%m%d_%H%M%S")
        history_doc_ref = db.collection(COLLECTION_NAME).document(history_doc_id)
        history_doc_ref.set(document_data)
        
        print(f"✅ Đã lưu Snapshot thành công. Số lượng tài khoản: {len(accounts_list)}. ID Dashboard: {SESSION_DOC_ID}, ID History: {history_doc_id}")
    except Exception as e:
        print(f"❌ Lỗi khi lưu Snapshot vào Firestore: {e}")

def save_open_trades_summary(db, open_trades_data):
    """Tạo và lưu mảng tóm tắt số lệnh đang mở vào collection riêng."""
    
    # Ở đây chúng ta vẫn phải tìm mảng có key là 'accounts' để lấy trades[] bên trong
    # Tuy nhiên, chúng ta có thể dùng find_account_list để bao quát
    accounts_with_trades_list = find_account_list(open_trades_data)
    
    accounts_with_trades = {}
    
    if accounts_with_trades_list:
        for acc in accounts_with_trades_list:
            account_id_long = acc.get('id') 
            trades = acc.get('trades', [])
            
            if account_id_long:
                # Tìm ID ngắn (phần trước dấu gạch ngang)
                short_id_match = str(account_id_long).split('-')[0]
                accounts_with_trades[short_id_match] = {
                    'account_id': short_id_match, 
                    'open_trades_count': len(trades)
                }

        open_trades_summary_list = list(accounts_with_trades.values())
        
        if open_trades_summary_list:
            try:
                current_time = datetime.now()
                doc_id = TRADES_DOC_ID
                summary_document = {
                    'timestamp': current_time.isoformat(),
                    'data': open_trades_summary_list, 
                    'success': open_trades_data.get('error') is False
                }
                doc_ref = db.collection(OPEN_TRADES_SUMMARY_COLLECTION).document(doc_id)
                doc_ref.set(summary_document)
                print("✅ Mảng JSON Tóm Tắt Lệnh Đang Mở Đã Tạo:")
                print(json.dumps(open_trades_summary_list, indent=4))
                print(f"✅ Đã lưu Mảng Tóm Tắt thành công vào Collection '{OPEN_TRADES_SUMMARY_COLLECTION}' với ID: {doc_id}")
                
            except Exception as e:
                print(f"❌ Lỗi khi lưu Mảng Tóm Tắt vào Firestore: {e}")
    else:
        print("⚠️ Bỏ qua bước Lưu Mảng Tóm Tắt: Danh sách rỗng.")


def run_data_collection():
    """Thực hiện toàn bộ quy trình thu thập và lưu dữ liệu."""
    
    account_ids_list = []

    try:
        # 1. Khởi tạo Firebase
        db = initialize_firebase()
        
        # 2. Đăng nhập để lấy Session ID
        session_id = get_session_id()
        if not session_id:
            print("❌ Không có Session ID, dừng quy trình.")
            return

        # 3. Lấy dữ liệu Snapshot tài khoản
        print("⏳ Đang lấy dữ liệu Snapshot Tài khoản...")
        # Lấy dữ liệu
        account_snapshot_data = fetch_data(GET_ACCOUNTS_API_BASE, session_id) 
        
        if account_snapshot_data:
            # Sửa logic để lấy danh sách tài khoản một cách linh hoạt
            accounts_list = find_account_list(account_snapshot_data)
            
            if accounts_list:
                save_snapshot_to_firestore(db, account_snapshot_data)
                
                # TRÍCH XUẤT TẤT CẢ ACCOUNT ID cho bước tiếp theo
                account_ids_list = [
                    str(acc.get('id')) for acc in accounts_list
                    if acc.get('id') is not None
                ]
                
                if not account_ids_list:
                    print("⚠️ Không tìm thấy bất kỳ ID tài khoản nào để lấy lệnh đang mở.")
                    return

            else:
                 print("❌ Lỗi khi lấy dữ liệu Snapshot hoặc không có tài khoản nào.")
                 return
        else:
             return

        # 4. Lấy dữ liệu Lệnh Đang Mở (Open Trades)
        print("⏳ Đang lấy dữ liệu Lệnh Đang Mở...")
        
        # GẮN THAM SỐ accountIds = chuỗi các ID cách nhau bằng dấu phẩy
        account_ids_param = ",".join(account_ids_list)
        
        open_trades_data = fetch_data(
            GET_OPEN_TRADES_API_BASE, 
            session_id, 
            accountIds=account_ids_param 
        )
        
        if open_trades_data:
            save_open_trades_summary(db, open_trades_data)
        else:
            pass 

    except Exception as e:
        print(f"‼️ LỖI NGHIÊM TRỌNG TRONG QUÁ TRÌNH CHẠY: {e}. Vui lòng kiểm tra lại cấu hình.")

    print("-" * 40)
    print("🏁 Quy trình cho vòng chạy này hoàn tất.")


# --- THỰC THI (MAIN EXECUTION) ---
if __name__ == '__main__':
    
    print("\n" + "#" * 60)
    print("🚀 Bắt đầu Chế độ Chạy Một Lần theo Lịch trình (GitHub Actions).")
    print("#" * 60)
    
    try:
        run_data_collection() 
    
    except Exception as e:
        print(f"\n‼️ FATAL ERROR: Lỗi không xác định xảy ra: {e}")
    
    print("\n" + "~" * 60)
    print("🏁 Tập lệnh đã hoàn thành và sẽ kết thúc.")
    print("~" * 60)
