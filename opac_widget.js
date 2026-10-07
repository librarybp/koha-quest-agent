/* Library Guide widget for the Koha OPAC.
 * Paste into Administration > System preferences > OPACUserJS.
 * Set AGENT_URL to the address of agent.py (use HTTPS in production). */
(function () {
  var AGENT_URL = "https://YOUR-AGENT-HOST:8765";
  var token = sessionStorage.getItem("lg_token");
  var history = [];

  var css = "#lg-btn{position:fixed;right:20px;bottom:20px;z-index:9999;background:#1f5f99;color:#fff;border:0;border-radius:24px;padding:10px 18px;font-size:15px;cursor:pointer}" +
    "#lg-box{position:fixed;right:20px;bottom:70px;z-index:9999;width:340px;max-width:92vw;height:460px;background:#fff;border:1px solid #ccc;border-radius:10px;display:none;flex-direction:column;box-shadow:0 4px 18px rgba(0,0,0,.15)}" +
    "#lg-log{flex:1;overflow:auto;padding:10px;font-size:14px}#lg-log p{margin:6px 0;white-space:pre-wrap}" +
    ".lg-u{text-align:right;color:#1f5f99}.lg-a{color:#222}#lg-form{display:flex;border-top:1px solid #eee}" +
    "#lg-in{flex:1;border:0;padding:10px;font-size:14px}#lg-send{border:0;background:#1f5f99;color:#fff;padding:0 14px}";
  var s = document.createElement("style"); s.textContent = css; document.head.appendChild(s);

  var btn = document.createElement("button"); btn.id = "lg-btn"; btn.textContent = "Library Guide";
  var box = document.createElement("div"); box.id = "lg-box";
  box.innerHTML = '<div style="padding:10px;border-bottom:1px solid #eee;font-weight:600">Library Guide (AI)</div>' +
    '<div id="lg-log"></div><form id="lg-form"><input id="lg-in" autocomplete="off" placeholder="Ask or type: show me quests">' +
    '<button id="lg-send">Send</button></form>';
  document.body.appendChild(btn); document.body.appendChild(box);
  var log = box.querySelector("#lg-log"), input = box.querySelector("#lg-in");

  function say(text, who) {
    var p = document.createElement("p"); p.className = who === "u" ? "lg-u" : "lg-a";
    p.textContent = text; log.appendChild(p); log.scrollTop = log.scrollHeight;
  }
  function post(path, body) {
    return fetch(AGENT_URL + path, {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body)}).then(function (r) { return r.json().then(function (j) { j._status = r.status; return j; }); });
  }
  function askLogin() {
    say("Please log in with your library user ID and password to use the guide.", "a");
    var u = prompt("Library user ID"); if (!u) return;
    var pw = prompt("Password"); if (!pw) return;
    post("/login", {userid: u, password: pw}).then(function (j) {
      if (j.token) { token = j.token; sessionStorage.setItem("lg_token", token); say("Logged in. How can I help?", "a"); }
      else say("Login failed. Please check your details.", "a");
    });
  }

  btn.onclick = function () {
    var open = box.style.display === "flex"; box.style.display = open ? "none" : "flex";
    if (!open && !token) askLogin();
  };
  box.querySelector("#lg-form").onsubmit = function (e) {
    e.preventDefault(); var text = input.value.trim(); if (!text) return;
    if (!token) { askLogin(); return; }
    input.value = ""; say(text, "u"); say("...", "a");
    post("/chat", {token: token, message: text, history: history}).then(function (j) {
      log.removeChild(log.lastChild);
      if (j._status === 401) { token = null; sessionStorage.removeItem("lg_token"); askLogin(); return; }
      var reply = j.reply || "Sorry, something went wrong.";
      say(reply, "a");
      history.push({role: "user", content: text}, {role: "assistant", content: reply});
      history = history.slice(-10);
    });
  };
})();
