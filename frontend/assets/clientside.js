window.dash_clientside = Object.assign({}, window.dash_clientside, {
    clientside: {
        recordAudio: function (n_clicks, current_value) {
            if (!n_clicks) {
                return window.dash_clientside.no_update;
            }

            // Check browser support
            var SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            if (!SpeechRecognition) {
                alert("Sorry, your browser does not support voice input. Please try Chrome, Edge, or Safari.");
                return window.dash_clientside.no_update;
            }

            // Provide visual feedback (optional: could toggle a class on the button via another callback, 
            // but for now let's rely on browser permission indicators)
            var btn = document.getElementById("mic-btn");
            if (btn) btn.classList.add("listening");

            return new Promise((resolve, reject) => {
                var recognition = new SpeechRecognition();
                recognition.lang = 'en-US';
                recognition.interimResults = false;
                recognition.maxAlternatives = 1;

                recognition.start();

                recognition.onresult = function (event) {
                    var text = event.results[0][0].transcript;
                    // Append to existing text if any? Or replace? 
                    // Usually voice query is a full sentence. Let's replace for clarity, 
                    // or append with space if needed. Let's replace to be simple.
                    resolve(text);
                    if (btn) btn.classList.remove("listening");
                };

                recognition.onspeechend = function () {
                    recognition.stop();
                    if (btn) btn.classList.remove("listening");
                };

                recognition.onerror = function (event) {
                    console.error("Speech recognition error", event.error);
                    if (btn) btn.classList.remove("listening");
                    resolve(window.dash_clientside.no_update);
                };
            });
        }
    }
});
