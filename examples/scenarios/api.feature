@api
Feature: Orders API
  Signed-in customers place orders through the JSON API.

  Background:
    Given the client sends POST "/login" with:
      """
      {"username": "bob", "password": "bob-password"}
      """
    And the client uses the token from "token"

  Scenario: Health check
    When the client sends GET "/health"
    Then the response status is 200
    And the response field "status" is "ok"

  Scenario: Placing an order
    When the client sends POST "/orders" with:
      """
      {"product": "pear", "quantity": 4}
      """
    Then the response status is 201
    And the response header "Content-Type" contains "json"
    And the response field "product" is "pear"
    And the response field "quantity" is "4"
    And the response field "total" is "6.0"
    And the response field "id" exists

  Scenario Outline: Invalid orders are rejected: <problem>
    When the client sends POST "/orders" with:
      """
      {"product": "<product>", "quantity": <quantity>}
      """
    Then the response status is 422
    And the response field "errors" has 1 items
    And the response field "errors[0]" is "<error>"

    Examples:
      | problem         | product | quantity | error                                    |
      | unknown product | banana  | 1        | product must be one of: apple, pear, plum |
      | too many        | apple   | 11       | quantity must be an integer from 1 to 10  |

  Scenario: Orders need a valid token
    When the client uses bearer token "not-a-real-token"
    And the client sends GET "/orders"
    Then the response status is 401
    And the response field "error" is "Missing or invalid token"
