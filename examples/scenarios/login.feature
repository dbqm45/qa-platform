@smoke
Feature: Login
  Registered customers sign in to see their dashboard.

  Background:
    Given the user opens "/login"

  Scenario: Successful login
    When the user fills "Username" with "alice"
    And the user fills "Password" with "correct-password"
    And the user clicks "Log in"
    Then the URL is "/dashboard"
    And "testid:greeting" is visible
    And the page shows "Welcome, Alice"

  Scenario: Invalid login
    When the user fills "Username" with "alice"
    And the user fills "Password" with "wrong-password"
    And the user clicks "Log in"
    Then the URL is "/login"
    And the page shows "Invalid username or password"
    And "Username" has value "alice"
    And "Password" has value ""

  Scenario: Account is locked after three failed sign-ins
    When the user fills "Username" with "carol"
    And the user fills "Password" with "wrong-1"
    And the user clicks "Log in"
    And the user fills "Password" with "wrong-2"
    And the user clicks "Log in"
    And the user fills "Password" with "wrong-3"
    And the user clicks "Log in"
    Then the page shows "Account locked"
