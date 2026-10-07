chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === "saveLink") {
    // Send message to native host
    chrome.runtime.sendNativeMessage(
      'jornal_eink.native_host',
      request.data,
      (response) => {
        if (chrome.runtime.lastError) {
          console.error("Native Messaging Error:", chrome.runtime.lastError.message);
          sendResponse({ success: false, error: chrome.runtime.lastError.message });
        } else {
          sendResponse({ success: true, data: response });
        }
      }
    );
    return true; // Keep message channel open for async response
  }
});
