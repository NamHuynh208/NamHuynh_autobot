'use strict';
const form = document.querySelector('form');
form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = form.querySelector('button');
  const status = document.querySelector('#login-status');
  button.disabled = true;
  status.textContent = 'Đang kiểm tra…';
  try {
    const response = await fetch('/api/login', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({password: form.elements.password.value})});
    if (response.ok) location.replace('/');
    else status.textContent = (await response.json()).detail || 'Không thể đăng nhập.';
  } catch { status.textContent = 'Không kết nối được. Kiểm tra mạng rồi thử lại.'; }
  finally { button.disabled = false; }
});
