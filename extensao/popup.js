document.addEventListener('DOMContentLoaded', async () => {
  const urlInput = document.getElementById('url');
  const langInput = document.getElementById('lang');
  const commentInput = document.getElementById('comment');
  const saveBtn = document.getElementById('saveBtn');
  const statusDiv = document.getElementById('status');

  // Get active tab
  let [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab) return;

  urlInput.value = tab.url;

  // Determine language
  let urlObj = new URL(tab.url);
  let lang = "";

  // Check Wikipedia subdomain
  let wikiMatch = urlObj.hostname.match(/([\w-]+)\.wikipedia\.org/i);
  if (wikiMatch) {
    lang = wikiMatch[1];
    langInput.value = lang;
  } else {
    // Inject script to get <html lang>
    try {
      let results = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: () => {
          let htmlTag = document.documentElement;
          return htmlTag.getAttribute('lang');
        }
      });
      if (results && results[0] && results[0].result) {
        // e.g. "pt-BR" -> "pt" or keeping it as is? "pt-br"
        lang = results[0].result.split('-')[0].toLowerCase();
        langInput.value = lang;
      }
    } catch (e) {
      console.error("Could not inject script to get language", e);
    }
  }

  saveBtn.addEventListener('click', () => {
    let finalUrl = urlInput.value;
    let finalLang = langInput.value.trim();
    let finalComment = commentInput.value.trim();

    saveBtn.disabled = true;
    statusDiv.textContent = "Salvando...";

    chrome.runtime.sendMessage({
      action: "saveLink",
      data: {
        url: finalUrl,
        lang: finalLang,
        comment: finalComment
      }
    }, (response) => {
      if (chrome.runtime.lastError) {
        statusDiv.style.color = "red";
        statusDiv.textContent = "Erro: " + chrome.runtime.lastError.message;
        saveBtn.disabled = false;
        return;
      }

      if (response && response.success) {
        statusDiv.style.color = "green";
        statusDiv.textContent = "Salvo com sucesso!";
        setTimeout(() => window.close(), 1500);
      } else {
        statusDiv.style.color = "red";
        statusDiv.textContent = "Erro: " + (response ? response.error : "Desconhecido");
        saveBtn.disabled = false;
      }
    });
  });
});
