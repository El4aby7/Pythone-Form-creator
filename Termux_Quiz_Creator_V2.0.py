import os
import pickle
import json # For potential debugging
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Global Constants
SCOPES = ['https://www.googleapis.com/auth/forms.body']
TOKEN_PICKLE_FILE = 'token.pickle'
CREDENTIALS_JSON_FILE = 'Web.Credentials.json' # Ensure this file exists

def authenticate():
    """Handles Google OAuth 2.0 authentication."""
    print("Authenticating...")
    creds = None
    if os.path.exists(TOKEN_PICKLE_FILE):
        with open(TOKEN_PICKLE_FILE, 'rb') as token:
            try:
                creds = pickle.load(token)
            except (pickle.UnpicklingError, EOFError, AttributeError, ImportError, IndexError) as e:
                print(f"Error loading token from {TOKEN_PICKLE_FILE}. File might be corrupted or incompatible: {e}")
                creds = None # Ensure creds is None if loading fails

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                print("Refreshing expired credentials...")
                creds.refresh(Request())
            except Exception as e:
                print(f"Error refreshing credentials: {e}")
                creds = None
        else:
            if not os.path.exists(CREDENTIALS_JSON_FILE):
                print(f"Error: Credentials file '{CREDENTIALS_JSON_FILE}' not found.")
                print("Please download your OAuth 2.0 client secrets file from Google Cloud Console,")
                print(f"name it '{CREDENTIALS_JSON_FILE}', and place it in the same directory as this script.")
                return None
            try:
                print(f"No valid token found or token expired. Running authentication flow using {CREDENTIALS_JSON_FILE}...")
                flow = InstalledAppFlow.from_client_secrets_file(
                    CREDENTIALS_JSON_FILE, SCOPES)
                creds = flow.run_local_server(port=8080)
            except FileNotFoundError: # Should be caught by os.path.exists, but good to have as fallback
                print(f"Error: Credentials file '{CREDENTIALS_JSON_FILE}' not found during flow.")
                return None
            except Exception as e:
                print(f"Error during authentication flow: {e}")
                creds = None

        if creds:
            try:
                with open(TOKEN_PICKLE_FILE, 'wb') as token:
                    pickle.dump(creds, token)
                print("Authentication successful, token saved.")
            except Exception as e:
                print(f"Error saving token to {TOKEN_PICKLE_FILE}: {e}")
                # Proceed with creds even if saving fails, but inform user
        else:
            print("Authentication failed. Please ensure credentials are valid and the authentication flow can complete.")
            return None
    else:
        print("Using valid existing credentials.")
    return creds

def _create_form_and_set_quiz(service, form_title, document_title):
    """
    Creates a basic form and then configures it as a quiz.
    Returns (form_id, responder_uri, quiz_setup_success_boolean).
    quiz_setup_success_boolean is True if quiz setting succeeded, False otherwise.
    form_id and responder_uri will be None if form creation itself fails.
    """
    print(f"Creating form with title: '{form_title}'...")
    form_id_created = None
    responder_uri_created = None
    try:
        form_body = {
            "info": {
                "title": form_title,
                "documentTitle": document_title
            }
        }
        created_form_result = service.forms().create(body=form_body).execute()
        form_id_created = created_form_result['formId']
        responder_uri_created = created_form_result['responderUri']
        print(f"Form scaffold created successfully. Form ID: {form_id_created}")
    except HttpError as e:
        print(f"Error creating form scaffold: {e}. Check API permissions and quota.")
        return None, None, False # Form creation failed

    print(f"Configuring form '{form_id_created}' as a quiz...")
    try:
        quiz_setting_body = {
            "requests": [
                {
                    "updateSettings": {
                        "settings": {"quizSettings": {"isQuiz": True}},
                        "updateMask": "quizSettings" # Broader mask as specified
                    }
                }
            ]
        }
        service.forms().batchUpdate(
            formId=form_id_created,
            body=quiz_setting_body
        ).execute()
        print(f"Form '{form_id_created}' successfully configured as a quiz.")
        return form_id_created, responder_uri_created, True # Both steps succeeded
    except HttpError as e:
        print(f"Error updating form settings to quiz for form ID {form_id_created}: {e}")
        print(f"The form was created (ID: {form_id_created}, URI: {responder_uri_created}), but could not be set as a quiz.")
        return form_id_created, responder_uri_created, False # Quiz setup failed, but form exists

def _add_questions_to_form(service, form_id, questions_data):
    """Adds questions to the specified form."""
    if not questions_data:
        print("No questions data provided to add.")
        return True # Not a failure of this specific function

    print(f"Adding {len(questions_data)} questions to form '{form_id}'...")
    all_question_requests_list = []
    for i, (question_text, options_list, correct_option_index, points_value) in enumerate(questions_data):
        # Basic validation for question data (can be expanded)
        if not all([isinstance(question_text, str),
                    isinstance(options_list, list) and len(options_list) >= 2,
                    isinstance(correct_option_index, int) and 0 <= correct_option_index < len(options_list),
                    isinstance(points_value, int) and points_value > 0]):
            print(f"Warning: Skipping invalid question data format: Q: '{question_text}', Options: {len(options_list)}, Correct Idx: {correct_option_index}, Points: {points_value}")
            continue

        request = {
            "createItem": {
                "item": {
                    "title": question_text,
                    "questionItem": {
                        "question": {
                            "required": True,
                            "choiceQuestion": {
                                "type": "RADIO",
                                "options": [{"value": option_text} for option_text in options_list],
                                "shuffle": True
                            },
                            "grading": { # This section is crucial for quiz questions
                                "pointValue": points_value,
                                "correctAnswers": {
                                    "answers": [{"value": options_list[correct_option_index]}]
                                }
                            }
                        }
                    }
                },
                "location": {"index": i} # i is the loop index
            }
        }
        all_question_requests_list.append(request)

    if not all_question_requests_list:
        print("No valid questions to add after data validation.")
        return False # Considered a failure if no valid questions were processed

    try:
        # For debugging the request payload if issues persist:
        # print("---- BEGINNING OF QUESTION REQUEST BODY ----")
        # print(json.dumps({"requests": all_question_requests_list}, indent=2))
        # print("---- END OF QUESTION REQUEST BODY ----")

        service.forms().batchUpdate(
            formId=form_id,
            body={"requests": all_question_requests_list}
        ).execute()
        print("Questions added successfully to the form!")
        return True
    except HttpError as e:
        print(f"Error adding questions to form '{form_id}': {e}")
        # Potentially print the JSON payload that caused the error for detailed debugging
        # print("Failed request body for adding questions was:")
        # print(json.dumps({"requests": all_question_requests_list}, indent=2))
        return False

def main_logic():
    """Main logic for the Google Forms quiz creator script."""
    creds = authenticate()
    if not creds:
        print("Exiting script due to authentication failure.")
        return

    form_title = input("Enter the Form Title: ")
    document_title = input("Enter the Document Title (usually same as Form Title): ")

    # Hardcoded question data
    questions_data_hardcoded = [
        ("What is the capital of France?", ["Rome", "Paris", "Berlin", "Madrid"], 1, 10),
        ("Which planet is known as the Red Planet?", ["Earth", "Mars", "Jupiter", "Venus"], 1, 15),
        ("What is 2 + 2?", ["3", "4", "5", "6"], 1, 5),
        ("Who wrote 'Hamlet'?", ["Charles Dickens", "William Shakespeare", "Leo Tolstoy", "Mark Twain"], 1, 20)
    ]
    print(f"\n--- Using {len(questions_data_hardcoded)} Hardcoded Questions ---")

    if not questions_data_hardcoded:
        print("No questions were provided in the hardcoded list. Exiting script.")
        return

    print("\nBuilding Google Forms service...")
    service = None
    try:
        service = build('forms', 'v1', credentials=creds)
    except Exception as e: # Catch errors during service build
        print(f"Failed to build Google Forms API service: {e}")
        return

    form_id, responder_uri, quiz_setup_success = _create_form_and_set_quiz(service, form_title, document_title)

    if form_id is None:
        print("Form creation failed or initial setup prevented proceeding. Cannot add questions. Exiting.")
        return

    if not quiz_setup_success:
        print("Warning: Form was created, but an error occurred during quiz setup. Questions will be added, but the form might not be a quiz.")
        # Proceed to add questions as form_id is valid.

    questions_added_successfully = _add_questions_to_form(service, form_id, questions_data_hardcoded)

    print("\n--- Form Processing Summary ---")
    if responder_uri:
        print(f"Form URI: {responder_uri}")
    else: # Should only happen if form creation failed, which is handled above.
        print(f"Form ID: {form_id}")

    if quiz_setup_success:
        print("Quiz setup: Successful")
    else:
        print("Quiz setup: Failed (Form may not be a quiz, or was only partially configured as one).")

    if questions_added_successfully:
        print("Adding questions: Successful")
        print("Process completed.")
    else:
        print("Adding questions: Failed")
        print("The form may be partially created or configured. Please check manually.")

if __name__ == '__main__':
    main_logic()
