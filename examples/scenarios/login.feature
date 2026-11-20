@smoke
Feature: Login

  Background:
    Given the login page is open

  Scenario: Successful login
    When the user signs in as "alice" with password "correct-password"
    Then the dashboard is shown
    And the greeting contains "Alice"
