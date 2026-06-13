import streamlit as st
import psycopg2
import psycopg2.errors
import pandas as pd

# ==========================================
# 1. 資料庫連線設定 
# ==========================================
def get_db_connection():
    conn = psycopg2.connect(st.secrets["general"]["db_uri"])
    return conn
# ==========================================
# 2. 初始化 Session State (身分驗證狀態管理)
# ==========================================
if 'user_id' not in st.session_state:
    st.session_state['user_id'] = None
if 'username' not in st.session_state:
    st.session_state['username'] = None

# ==========================================
# 3. 側邊欄：會員登入與註冊系統
# ==========================================
st.sidebar.title("個人選單")

if st.session_state['user_id'] is None:
    auth_mode = st.sidebar.radio("切換功能", ["會員登入", "註冊新會員"])

    # 會員登入表單
    if auth_mode == "會員登入":
        auth_username = st.sidebar.text_input("帳號 (Username)", key="auth_user")
        auth_password = st.sidebar.text_input("密碼 (Password)", type="password", key="auth_pass")
        if st.sidebar.button("登入"):
            if auth_username and auth_password:
                conn = get_db_connection()
                cursor = conn.cursor()
                # 📌 亮點：PostgreSQL 參數化查詢一律使用 %s，且表名皆為安全小寫
                cursor.execute("SELECT user_id, username FROM users WHERE username = %s AND password_hash = %s", (auth_username, auth_password))
                user = cursor.fetchone()
                cursor.close()
                conn.close()

                if user:
                    st.session_state['user_id'] = user[0]
                    st.session_state['username'] = user[1]
                    st.sidebar.success(f"歡迎回來，{user[1]}！")
                    st.rerun()
                else:
                    st.sidebar.error("帳號或密碼錯誤！")
            else:
                st.sidebar.warning("請輸入帳號與密碼")

    # 註冊新會員表單
    elif auth_mode == "註冊新會員":
        auth_username = st.sidebar.text_input("帳號 (Username)", max_chars=20, key="auth_user")
        auth_password = st.sidebar.text_input("密碼 (Password)", type="password", key="auth_pass")
        auth_email = st.sidebar.text_input("電子信箱 (Email)", key="auth_email")
        if st.sidebar.button("註冊"):
            if auth_username and auth_password:
                conn = get_db_connection()
                cursor = conn.cursor()
                try:
                    cursor.execute("INSERT INTO users (username, password_hash, email) VALUES (%s, %s, %s)", (auth_username, auth_password, auth_email))
                    conn.commit()
                    st.sidebar.success("註冊成功！請切換至登入畫面。")
                except psycopg2.errors.UniqueViolation:
                    st.sidebar.error("此帳號已被註冊！")
                finally:
                    cursor.close()
                    conn.close()
            else:
                st.sidebar.warning("帳號與密碼為必填項目")
else:
    st.sidebar.write(f"👤 當前登入：**{st.session_state['username']}**")
    if st.sidebar.button("登出系統"):
        st.session_state['user_id'] = None
        st.session_state['username'] = None
        st.rerun()


# ==========================================
# 4. 建立日常記帳局部刷新組件 (Fragment 1)
# ==========================================
@st.fragment
def render_transaction_form(current_user_id):
    st.subheader("📝 新增日常收支")

    local_conn = get_db_connection()

    try:
        # 撈取該使用者目前擁有的帳戶
        user_acc_query = f"SELECT ua.account_id, b.bank_id, b.bank_name, ua.account_name, ua.balance FROM user_accounts ua JOIN banks b ON ua.bank_id = b.bank_id WHERE ua.user_id = {current_user_id}"
        user_acc_df = pd.read_sql(user_acc_query, local_conn)

        # 撈取所有記帳分類 (將原本的 type 修正為正確的欄位名稱 category_type)
        categories_df = pd.read_sql("SELECT category_id, category_name, category_type FROM categories", local_conn)
        categories_df['display'] = categories_df['category_name'] + " (" + categories_df['category_type'] + ")"

        if user_acc_df.empty:
            st.info("您目前尚未綁定任何銀行帳戶，請先在最下方完成綁定以開始記帳。")
        else:
            user_acc_df['display'] = user_acc_df.apply(lambda row: f"{row['bank_id']} {row['account_name']} (餘額: {int(float(row['balance']))})", axis=1)

            # 使用三欄讓使用者同時選擇帳戶、收支類型與分類
            col_acc, col_type, col_cat = st.columns([3, 2, 3])
            with col_acc:
                chosen_acc = st.selectbox("帳戶選擇", options=user_acc_df.to_dict('records'), format_func=lambda x: x['display'])
            with col_type:
                chosen_type = st.radio("收支類型", options=["支出", "收入"], horizontal=True)
            with col_cat:
                filtered_cat_df = categories_df[categories_df['category_type'] == chosen_type]
                chosen_cat = st.selectbox("選擇交易分類", options=filtered_cat_df.to_dict('records'), format_func=lambda x: x['category_name'])

            tx_amount = st.number_input("交易金額", min_value=0.00, value=0.00, step=10.0)
            tx_desc = st.text_input("備註說明", placeholder="例如：購物、N月薪水")

            # 呼叫雲端建好的預存程序 (sp_InsertTransaction)
            if st.button("確認送出記帳"):
                cursor = local_conn.cursor()
                try:
                    cursor.execute(
                        "CALL sp_inserttransaction (%s, %s, %s::numeric, %s::text);",
                        (int(chosen_acc['account_id']), int(chosen_cat['category_id']), float(tx_amount), str(tx_desc))
                    )
                    local_conn.commit()
                    st.success("記帳成功！資產餘額已自動計算更新。")
                    cursor.close()
                    st.rerun()

                except psycopg2.Error as e:
                    err_msg = str(e)
                    if "記帳失敗" in err_msg:
                        clean_msg = err_msg.split("CONTEXT:")[0].strip()
                    else:
                        clean_msg = "餘額不足！"
                    st.error(f"⚠️ {clean_msg}")
                finally:
                    if 'cursor' in locals(): cursor.close()
    finally:
        local_conn.close()


# ==========================================
# 5. 建立開戶綁定銀行局部刷新組件
# ==========================================
@st.fragment
def render_bank_binding_form(current_user_id):
    st.subheader("綁定銀行帳戶")
    with st.expander("點擊展開 : 開戶功能"):
        local_conn = get_db_connection()
        try:
            all_banks_df = pd.read_sql("SELECT bank_id, bank_name FROM banks", local_conn)
            all_banks_df['display'] = all_banks_df['bank_id'] + " - " + all_banks_df['bank_name']

            selected_bank = st.selectbox("選擇要綁定的銀行", options=all_banks_df.to_dict('records'), format_func=lambda x: x['display'])
            custom_acc_name = st.text_input("自訂帳戶別名 (例如：我的薪轉戶、生活費帳戶)", placeholder="可不填")
            init_balance = st.number_input("初始帳戶餘額", min_value=0.0, step=100.0)

            if st.button("確認綁定銀行"):
                chosen_bank_code = selected_bank['bank_id']
                final_alias = custom_acc_name.strip() if custom_acc_name.strip() else selected_bank['bank_name'].strip()

                user_acc_df = pd.read_sql(f"SELECT bank_id FROM user_accounts WHERE user_id = {current_user_id}", local_conn)
                exsiting_banks = user_acc_df['bank_id'].astype(str).values if not user_acc_df.empty else []

                if str(chosen_bank_code) in exsiting_banks:
                    st.error("您已經綁定過此銀行了！請選擇其他銀行或刪除原有帳戶後再試。")
                else:
                    cursor = local_conn.cursor()
                    try:
                        cursor.execute(
                            "INSERT INTO user_accounts (user_id, bank_id, account_name, balance) VALUES (%s, %s, %s, %s)",
                            (current_user_id, chosen_bank_code, final_alias, init_balance)
                        )
                        local_conn.commit()
                        st.success(f"🎉 成功綁定 {final_alias} 帳戶！")
                        cursor.close()
                        st.rerun()
                    except Exception as e:
                        st.error(f"綁定失敗：{e}")
                    finally:
                        if 'cursor' in locals(): cursor.close()
        finally:
            local_conn.close()


# ==========================================
# 6. 主畫面流程調度中心 (需身分驗證登入後方可見)
# ==========================================
if st.session_state['user_id'] is not None:
    current_user_id = st.session_state['user_id']
    st.title(f"📊 {st.session_state['username']} 的個人財務管理系統")

    # 開啟大畫面主流程所需的連線
    conn = get_db_connection()

    # ------------------------------------------
    # 顯示總資產餘額
    # ------------------------------------------
    user_balance_query = f"SELECT ua.account_id, b.bank_id, b.bank_name, ua.account_name, ua.balance FROM user_accounts ua JOIN banks b ON ua.bank_id = b.bank_id WHERE ua.user_id = {current_user_id}"
    user_balance_df = pd.read_sql(user_balance_query, conn)
    if user_balance_df.empty:
        total_balance = 0.0
    else:
        total_balance = user_balance_df['balance'].sum()
    col_metric,col_privacy = st.columns([3,1])

    with col_privacy:
        st.write("")
        hide_balance = st.toggle("隱藏餘額", value = False , key = "privacy_mode")

    with col_metric:
        if hide_balance:
            st.metric(label="💰總資產餘額 (隱藏)", value="****** 元")
        else:
            st.metric(label="💰總資產餘額", value=f"{total_balance:,.2f} 元")
    st.markdown("---")

    # ------------------------------------------
    # 執行日常記帳局部組件
    # ------------------------------------------
    render_transaction_form(current_user_id)
    st.markdown("---")

    # ------------------------------------------
    # 功能 B：歷史明細與錯帳刪除
    # ------------------------------------------
    st.subheader("📜 歷史記帳明細與刪除")

    view_query = f"SELECT tx_id, bank_id, bank_name, account_name, category_name, transaction_type, amount, tx_date, description FROM v_usertransactions WHERE user_id = {current_user_id} ORDER BY tx_date DESC"

    try:
        temp_cursor = conn.cursor()
        history_df = pd.read_sql(view_query, conn)
        temp_cursor.close()
    except Exception:
        conn.rollback()
        backup_query = f"SELECT t.tx_id, ua.bank_id, b.bank_name, ua.account_name, c.category_name, t.transaction_type, t.amount, t.tx_date, t.description FROM transactions t JOIN user_accounts ua ON t.account_id = ua.account_id JOIN banks b ON ua.bank_id = b.bank_id JOIN categories c ON t.category_id = c.category_id WHERE ua.user_id = {current_user_id} ORDER BY t.tx_date DESC"
        try:
            history_df = pd.read_sql(backup_query, conn)
        except Exception:
            conn.rollback()
            history_df = pd.DataFrame()

    if history_df.empty:
        st.write("目前尚無任何交易紀錄。")
    else:
        history_df['tx_date'] = pd.to_datetime(history_df['tx_date'])  # 確保日期格式正確
        current_date = pd.Timestamp.now()
        current_year = current_date.year
        current_month = current_date.month

        if current_month == 1:
            prev_month = 12
            prev_year = current_year - 1
        else:
            prev_month = current_month - 1
            prev_year = current_year

        start_of_prev_month = pd.Timestamp(prev_year, prev_month, 1)
        filtered_df = history_df[history_df['tx_date'] >= start_of_prev_month]

        if filtered_df.empty:
            st.write(f"目前尚無 {prev_year} 年 {prev_month} ~ {current_month} 月的交易紀錄。")
        else:
            show_table = filtered_df.drop(columns=['tx_id'])  # 隱藏交易序號
            show_table = show_table.rename(columns={
                'bank_id': '銀行代碼', 'bank_name': '銀行名稱',
                'account_name': '帳戶別名', 'category_name': '分類',
                'transaction_type': '收支類型', 'amount': '金額',
                'tx_date': '交易時間', 'description': '備註'
            })
            show_table['交易時間'] = pd.to_datetime(show_table['交易時間']).dt.strftime('%Y-%m-%d')
            st.dataframe(show_table, use_container_width=True)

            # Trigger 自動校正餘額刪除區
            st.subheader("⚠️ 記錯帳刪除區")
            tx_to_delete = st.selectbox(
                "選擇欲刪除的交易序號",
                options=history_df.to_dict('records'),
                format_func=lambda x: f"時間: {x['tx_date'].strftime('%Y-%m-%d')} | 帳戶: {x['account_name']} | 分類: {x['category_name']} | 金額: {int(float(x['amount']))} | 類型: {x['transaction_type']}"
            )

            if st.button("確認刪除此筆交易"):
                cursor = conn.cursor()
                try:
                    # 刪除交易紀錄，雲端設定好的 Trigger 會隔空自動將金額校正扣回或加回帳戶餘額！
                    cursor.execute("DELETE FROM transactions WHERE tx_id = %s", (tx_to_delete['tx_id'],))
                    conn.commit()
                    st.success(f"交易序號 {tx_to_delete['tx_id']} 已刪除！資料庫 Trigger 已跨時空將金額完美校正。")
                    cursor.close()
                    st.rerun()
                except Exception as e:
                    st.error(f"刪除失敗：{e}")
                finally:
                    if 'cursor' in locals(): cursor.close()

    st.markdown("---")

    # ------------------------------------------
    # 執行開戶綁定局部組件
    # ------------------------------------------
    render_bank_binding_form(current_user_id)
    st.markdown("---")

    # 主流程結束，隨手將主連線關閉
    conn.close()

else:
    st.title("💰 歡迎使用螞蟻記帳系統")
    st.info("👈 請先透過左側邊欄進行【會員登入】或【註冊新會員】以開始使用系統。")
