from flask import Flask, render_template, request, redirect, jsonify, url_for, json, render_template
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import timedelta

app = Flask(__name__)

DB_CONFIG = {
    "dbname": "Testing",
    "user": "postgres",
    "password": "314159265359o",
    "host": "localhost",
    "port": "5432"
}


def get_db_connection():
    return psycopg2.connect(**DB_CONFIG)

@app.route('/search', methods=['POST'])
def search_test():
    code = request.form.get('code')  # Используем get, чтобы избежать ошибки KeyError
    if not code:
        return 'Missing form field: code', 400  # Возвращаем ошибку, если поле пустое или не найдено

    conn = get_db_connection()
    cursor = conn.cursor()

    # Проверяем, есть ли тест с таким ID
    cursor.execute("SELECT * FROM tests WHERE code = %s", (code,))
    test = cursor.fetchone()
    cursor.close()
    conn.close()

    if test:
        # Перенаправляем на страницу с тестом
        return redirect(url_for('index_for_students', code=code))
    else:
        return 'Test not found', 404


@app.route('/index_for_students/<code>')
def index_for_students(code):
    conn = get_db_connection()
    cursor = conn.cursor()

    # Получаем тест с его названием и продолжительностью
    cursor.execute("SELECT test_id, test_name, duration FROM tests WHERE code = %s", (code,))
    test = cursor.fetchone()

    if not test:
        return 'Test not found', 404

    test_id, test_name, duration = test  # duration в формате HH:MM:SS

    # Преобразуем время в секунды
    hours, minutes, seconds = map(int, str(duration).split(":"))
    duration_seconds = timedelta(hours=hours, minutes=minutes, seconds=seconds).total_seconds()

    # Получаем вопросы с ответами
    cursor.execute("""
        SELECT q.question_id, q.question_name, a.answer_name 
        FROM questions q
        JOIN answers a ON q.question_id = a.question_id
        WHERE q.test_id = %s
    """, (test_id,))

    rows = cursor.fetchall()

    # Формируем структуру данных
    questions_dict = {}
    for question_id, question_name, answer_name in rows:
        if question_id not in questions_dict:
            questions_dict[question_id] = {"question": question_name, "options": []}
        questions_dict[question_id]["options"].append(answer_name)

    questions = list(questions_dict.values())

    cursor.close()
    conn.close()

    return render_template('index_for_students.html', test_name=test_name, duration=int(duration_seconds), questions=questions)

@app.route("/")
def index():
    return render_template("lending.html")

@app.route("/do_test")
def do_test():
    return render_template("index_for_students.html")

@app.route("/create_test")
def create_test():
    return render_template("index_for_teachers.html")

@app.route("/all_tests")
def all_tests():
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT test_id, test_name, appointment_date FROM tests")  # test_id здесь уже есть
            tests = cursor.fetchall()
    return render_template("all_tests.html", tests=tests)

@app.route("/delete_test/<int:test_id>", methods=["DELETE"])
def delete_test(test_id):
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM answers WHERE question_id IN (SELECT question_id FROM questions WHERE test_id = %s)", (test_id,))
                cursor.execute("DELETE FROM questions WHERE test_id = %s", (test_id,))
                cursor.execute("DELETE FROM tests WHERE test_id = %s", (test_id,))
            conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/edit_test/<int:test_id>")
def edit_test(test_id):
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT test_name FROM tests WHERE test_id = %s", (test_id,))
            test = cursor.fetchone()

            cursor.execute("""
                SELECT q.question_id, q.question_name, a.answer_id, a.answer_name
                FROM questions q
                LEFT JOIN answers a ON q.question_id = a.question_id
                WHERE q.test_id = %s
            """, (test_id,))
            questions = cursor.fetchall()

    structured_questions = []
    for question in questions:
        question_id = question["question_id"]
        question_text = question["question_name"]
        answer_text = question["answer_name"]

        if not any(q["question_text"] == question_text for q in structured_questions):
            structured_questions.append({
                "question_text": question_text,
                "answers": [answer_text]
            })
        else:
            for q in structured_questions:
                if q["question_text"] == question_text:
                    q["answers"].append(answer_text)

    return render_template("index_for_teachers.html", test_name=test["test_name"], questions=structured_questions, test_id=test_id)


@app.route("/save_test", methods=["POST"])
def save_test():
    data = request.json
    test_name = data.get("test_name")
    appointment_date = data.get("appointment_date", "").strip()
    start_time = data.get("start_time")
    end_time = data.get("end_time")
    questions = data.get("questions", [])
    code = data.get("code")  # Получаем код
    print("Полученные данные:", json.dumps(data, indent=2, ensure_ascii=False))

    if not test_name or not appointment_date or not start_time or not end_time or not questions or not code:
        return jsonify({"error": "Некорректные данные. Проверьте заполненность всех полей."}), 400

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO tests (test_name, appointment_date, start_time, end_time, code)
                    VALUES (%s, %s, %s, %s, %s) RETURNING test_id
                    """, (test_name, appointment_date, start_time, end_time, code)
                )
                test_id = cursor.fetchone()[0]

                for question in questions:
                    question_text = question.get("question_text")
                    if not question_text:
                        continue

                    cursor.execute(
                        """
                        INSERT INTO questions (test_id, question_name)
                        VALUES (%s, %s) RETURNING question_id
                        """, (test_id, question_text)
                    )
                    question_id = cursor.fetchone()[0]

                    for answer in question.get("answers", []):
                        answer_text = answer.get("answer_name")
                        is_correct = answer.get("is_correct", False)

                        cursor.execute(
                            """
                            INSERT INTO answers (question_id, answer_name, is_correct)
                            VALUES (%s, %s, %s)
                            """, (question_id, answer_text, is_correct)
                        )

                conn.commit()

        return jsonify({"message": "Тест успешно сохранен!"})

    except Exception as e:
        print(e)
        return jsonify({"error": "Ошибка сохранения теста"}), 50


@app.route('/test/<code>')
def test(code):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT q.question_id, q.question_name, 
               array_agg(a.answer_name), 
               array_agg(a.is_correct)  
        FROM questions q
        JOIN answers a ON q.question_id = a.question_id
        JOIN tests t ON q.test_id = t.test_id
        WHERE t.code = %s
        GROUP BY q.question_id, q.question_name
    """, (code,))

    questions = []
    for row in cursor.fetchall():
        question_id, question_text, options, correct_flags = row
        correct_answers = [bool(c) for c in correct_flags]
        questions.append({
            "question_id": question_id,
            "question": question_text,
            "options": options,
            "correct_answers": correct_answers
        })

    cursor.close()
    conn.close()

    return render_template(
        "index_for_students.html",
        test_name="Тест",
        duration=600,
        questions=questions,
        code=code
    )

@app.route('/results/<code>', methods=['POST'])
def results(code):
    data = request.json
    if not data or 'answers' not in data:
        return jsonify({"error": "Invalid request"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT q.question_id, a.answer_name, a.is_correct
            FROM questions q
            JOIN answers a ON q.question_id = a.question_id
            JOIN tests t ON q.test_id = t.test_id
            WHERE t.code = %s
        """, (code,))
        rows = cursor.fetchall()

        if not rows:
            return jsonify({"error": "Test not found"}), 404

        correct_answers = {}
        for row in rows:
            if row[2]:
                correct_answers[row[0]] = row[1].strip().lower()

        print("Правильные ответы из базы данных:", rows)
        print("Словарь правильных ответов:", correct_answers)

        correct_count = 0
        for ans in data['answers']:
            question_id = ans['question_id']
            answer = ans['answer'].strip().lower()
            print(f"Сравнение: вопрос {question_id}, ответ {answer}, правильный ответ {correct_answers.get(question_id)}")
            if question_id in correct_answers and correct_answers[question_id] == answer:
                correct_count += 1

        total_questions = len(correct_answers)
        score = (correct_count / total_questions) * 100 if total_questions > 0 else 0

        print("Количество правильных ответов:", correct_count)
        print("Результат:", score)

        return jsonify({"score": round(score, 2)})

    except Exception as e:
        print(f"Ошибка: {e}")
        return jsonify({"error": "Internal server error"}), 500

    finally:
        cursor.close()
        conn.close()








@app.route('/results.html')
def show_results():
    score = request.args.get('score', '0')
    return f"<h1>Ваш результат:{score}%</h1>"



if __name__ == "__main__":
    app.run(debug=True, port=3000)
