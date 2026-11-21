Feature: Contact form
  Customers can send a message to the shop.

  Background:
    Given the user opens "/contact"

  Scenario: Sending a message
    When the user fills "Name" with "Alice"
    And the user fills "Email" with "alice@example.com"
    And the user selects "Delivery" in "Topic"
    And the user fills "Message" with "When will my order arrive?"
    And the user checks "I agree to be contacted"
    And the user clicks "Send"
    Then the page shows "Thank you, Alice!"

  Scenario Outline: Invalid input is rejected: <problem>
    When the user fills "Name" with "<name>"
    And the user fills "Email" with "<email>"
    And the user selects "Order question" in "Topic"
    And the user fills "Message" with "Hello"
    And the user checks "I agree to be contacted"
    And the user clicks "Send"
    Then the page shows "<error>"
    And "Name" has value "<name>"

    Examples:
      | problem       | name  | email             | error                |
      | missing name  |       | alice@example.com | Name is required     |
      | invalid email | Alice | alice.example.com | Email must contain @ |
