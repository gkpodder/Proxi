/*
When coding this file,
I referred to these resources:

https://www.w3schools.com/js/js_classes.asp

https://www.w3schools.com/js/js_htmldom_html.asp

https://www.w3schools.com/jsref/met_document_createelement.asp

https://www.w3schools.com/jsref/met_element_remove.asp

*/

class proxyInterface{
    constructor(){

        this.UIState = {
            idle: "Idle",
            listening: "Listening",
            waiting: "Waiting",
            displaying: "Displaying",
            error: "Error"
        };
        this.uiState;
        this.lastMsg;
        this.lastError;

        this.initUI();
    };

    initUI(){
        this.uiState = this.UIState.idle;
        this.lastMsg = "";
        this.lastError = null;
    };

    //the environment variable, display is both the screen
    //and console

    //the environment variable, inputChannel is a user's
    //keyboard

    //For implementation, s is a string
    updateView(s){
        this.uiState = s;
        const message = this.stateText(this.uiState);
        console.log(message);
    };

    //I am assuming BH-Feedback's OutputMode is TextOnly
    showMessage(msg){
        this.lastMsg = msg;
        this.uiState = this.UIState.displaying;
        //render element
        const messageContainer = document.getElementById("renderedMessage");
        messageContainer.innerHTML = msg;
    };

    promptUser(q){
        this.uiState = this.UIState.waiting;
        const promptContainer = document.getElementById("renderedPrompt");
        promptContainer.innerHTML = q;
        const inputContainer = document.createElement("input");
        const contentContainer = document.getElementById("contentContainer");
        contentContainer.appendChild(inputContainer);
    };

    //I am assuming st is a string
    showStatus(st){
        console.log(st);
    };

    //I am assuming clearScreen clears everything except for
    //"Module Implementation by Team 24"
    clearScreen(){
        this.uiState = this.UIState.idle;
        this.lastMsg = "";
        const contentContainer = document.getElementById("contentContainer");
        contentContainer.remove();
    };

    stateText(s){
        if (s == this.UIState.listening){
            return "Listening...";
        }else if (s == this.UIState.waiting){
            return "Waiting for input...";
        }else if (s == this.UIState.displaying){
            return "Processing...";
        }else if (s == this.UIState.idle){
            return "Idle";
        }else{
            return "Error";
        }
    }
};



