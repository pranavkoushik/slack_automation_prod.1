from automation import run_automation


if __name__ == "__main__":
    # Keeps local execution simple while reusing the same code Vercel runs.
    result = run_automation()
    print("Script executed successfully")
    print(result)
