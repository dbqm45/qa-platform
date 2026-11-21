Feature: Orders across API and UI
  An order placed through the API is visible on the customer's dashboard.

  Scenario: An order placed through the API appears on the dashboard
    Given the client sends POST "/login" with:
      """
      {"username": "alice", "password": "correct-password"}
      """
    And the client uses the token from "token"
    And the client sends POST "/orders" with:
      """
      {"product": "apple", "quantity": 3}
      """
    Then the response status is 201
    When the user opens "/login"
    And the user fills "Username" with "alice"
    And the user fills "Password" with "correct-password"
    And the user clicks "Log in"
    Then "testid:orders" is visible
    And the page shows "apple (quantity 3)"
