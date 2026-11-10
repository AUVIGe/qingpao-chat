(function () {
  'use strict';
  var input = document.getElementById('text');
  var row = document.querySelector('.composebox');
  var button = document.createElement('button');
  button.type = 'button';
  button.className = 'voice-input';
  button.setAttribute('aria-label', '语音转文字');
  button.title = '语音转文字';
  button.textContent = '🎙';
  row.insertBefore(button, input);
  var Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  var recognition = null;
  var listening = false;
  var original = '';
  function finish() {
    listening = false;
    button.classList.remove('listening');
    button.title = '语音转文字';
    button.setAttribute('aria-label', '语音转文字');
  }
  button.onclick = function () {
    if (input.disabled) { alert('请先选择好友'); return; }
    if (!Recognition) { alert('当前浏览器不支持语音转文字，请使用手机输入法的麦克风按钮。'); return; }
    if (listening) { recognition.stop(); return; }
    original = input.value;
    recognition = new Recognition();
    recognition.lang = 'zh-CN';
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.onstart = function () {
      listening = true;
      button.classList.add('listening');
      button.title = '正在聆听，点击结束';
      button.setAttribute('aria-label', button.title);
    };
    recognition.onresult = function (event) {
      var text = '';
      for (var i = 0; i < event.results.length; i++) text += event.results[i][0].transcript;
      input.value = original + text;
      input.dispatchEvent(new Event('input', { bubbles: true }));
    };
    recognition.onerror = function (event) {
      finish();
      if (event.error === 'not-allowed' || event.error === 'service-not-allowed') alert('请允许浏览器使用麦克风和语音识别。');
      else if (event.error !== 'no-speech' && event.error !== 'aborted') alert('语音识别失败，请重试或使用手机输入法的麦克风。');
    };
    recognition.onend = finish;
    try { recognition.start(); } catch (e) { finish(); alert('无法启动语音输入，请重试。'); }
  };
})();
