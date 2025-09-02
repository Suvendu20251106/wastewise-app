import streamlit as st
# Simulated user database with roles
users = {
    "ministry_user": {"password": "ministry_pass", "role": "ministry"},
    "citizen_user": {"password": "citizen_pass", "role": "citizen"},
    "employee_user": {"password": "employee_pass", "role": "employee"},
}
# Simulated data stores
waste_collection = []
rewards = {}
def login():
    st.title("Waste Management System Login")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    if st.button("Login"):
        if username in users and users[username]["password"] == password:
            st.session_state["username"] = username
            st.session_state["role"] = users[username]["role"]
            st.success(f"Logged in as {username} ({users[username]['role']})")
        else:
            st.error("Invalid username or password")
def logout():
    st.session_state.pop("username", None)
    st.session_state.pop("role", None)
    st.success("Logged out")
