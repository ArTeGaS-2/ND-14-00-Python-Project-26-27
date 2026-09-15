"use strict";
const $ = (s) => document.querySelector(s);
const h = (v) =>
  String(v ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const weekdays = [
  "Понеділок",
  "Вівторок",
  "Середа",
  "Четвер",
  "П’ятниця",
  "Субота",
  "Неділя",
];
const shortDays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"];
const months = [
  "січня",
  "лютого",
  "березня",
  "квітня",
  "травня",
  "червня",
  "липня",
  "серпня",
  "вересня",
  "жовтня",
  "листопада",
  "грудня",
];
function kyivToday() {
  const p = Object.fromEntries(
    new Intl.DateTimeFormat("en-CA", {
      timeZone: "Europe/Kyiv",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    })
      .formatToParts(new Date())
      .map((x) => [x.type, x.value]),
  );
  return new Date(+p.year, +p.month - 1, +p.day, 12);
}
function addDays(d, n) {
  const r = new Date(d);
  r.setDate(r.getDate() + n);
  return r;
}
function dayIndex(d) {
  return (d.getDay() + 6) % 7;
}
function mondayOf(d) {
  return addDays(d, -dayIndex(d));
}
function isoDate(d) {
  return (
    d.getFullYear() +
    "-" +
    String(d.getMonth() + 1).padStart(2, "0") +
    "-" +
    String(d.getDate()).padStart(2, "0")
  );
}
function parseDate(s) {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, m - 1, d, 12);
}
function fullDate(d) {
  return d.getDate() + " " + months[d.getMonth()] + " " + d.getFullYear();
}
function lessonCountLabel(n) {
  const a = n % 10,
    b = n % 100;
  return (
    n +
    " " +
    (b >= 11 && b <= 14
      ? "уроків"
      : a === 1
        ? "урок"
        : a >= 2 && a <= 4
          ? "уроки"
          : "уроків")
  );
}
// Налаштування перегляду. Уроки, оцінки та записи зберігає сервер.
const today = kyivToday();
let selectedDate =
    dayIndex(today) > 4 ? addDays(today, 7 - dayIndex(today)) : new Date(today),
  weekStart = mondayOf(selectedDate);
let mode = matchMedia("(max-width: 900px)").matches ? "day" : "week",
  userRole = "teacher",
  studentClass = "6-А",
  studentId = "";
let classes = [],
  students = [],
  lessons = [],
  weekRequest = 0,
  detailRequest = 0,
  activeDetails = null,
  editingLesson = null,
  ready = false,
  toastTimer;
const panel = $(".schedule-panel"),
  grid = $("#schedule"),
  dialog = $("#lesson-dialog");
function rememberView() {
  try {
    localStorage.setItem(
      "schedule-view-v1",
      JSON.stringify({ userRole, studentClass, studentId, mode }),
    );
  } catch {}
}
function restoreView() {
  try {
    const s = JSON.parse(localStorage.getItem("schedule-view-v1") || "{}");
    if (["teacher", "student"].includes(s.userRole)) userRole = s.userRole;
    if (classes.includes(s.studentClass)) studentClass = s.studentClass;
    if (
      students.some(
        (x) => x.id === s.studentId && x.class_name === studentClass,
      )
    )
      studentId = s.studentId;
    if (["day", "week"].includes(s.mode)) mode = s.mode;
  } catch {}
}
async function api(path, method = "GET", body) {
  const o = {
    method,
    headers: {
      "X-Demo-Role": path === "/api/bootstrap" ? "teacher" : userRole,
      "X-Student-Id": studentId,
    },
  };
  if (body !== undefined) {
    o.headers["Content-Type"] = "application/json";
    o.body = JSON.stringify(body);
  }
  let r, j;
  try {
    r = await fetch(path, o);
  } catch {
    throw new Error(
      "Немає зв’язку із сервером. Введені дані залишилися у формі.",
    );
  }
  try {
    j = await r.json();
  } catch {
    throw new Error("Сервер не повернув дані. Спробуй ще раз.");
  }
  if (!r.ok) throw new Error(j.error || "Не вдалося виконати дію.");
  return j;
}
function toast(text) {
  clearTimeout(toastTimer);
  const host =
    [...document.querySelectorAll("dialog[open]")].at(-1) || document.body;
  host.append($("#toast"));
  $("#toast").textContent = text;
  $("#toast").hidden = false;
  toastTimer = setTimeout(() => ($("#toast").hidden = true), 4500);
}
async function submitAction(form, error, action) {
  if (form.dataset.busy) return;
  form.dataset.busy = "true";
  error.textContent = "";
  const buttons = [...form.querySelectorAll('button[type="submit"]')];
  buttons.forEach((b) => (b.disabled = true));
  try {
    await action();
  } catch (e) {
    error.textContent = e.message;
  } finally {
    delete form.dataset.busy;
    buttons.forEach((b) => (b.disabled = false));
  }
}
function fillSelect(select, values, current, label = (x) => x) {
  select.replaceChildren();
  for (const x of values) {
    const o = document.createElement("option");
    o.value = typeof x === "string" ? x : x.id;
    o.textContent = label(x);
    select.append(o);
  }
  select.value = current;
}
function fillProfiles() {
  const roster = students.filter((s) => s.class_name === studentClass);
  if (!roster.some((s) => s.id === studentId)) studentId = roster[0]?.id || "";
  fillSelect($("#student-profile"), roster, studentId, (s) => s.name);
}
function lessonsOn(d) {
  return lessons.filter((l) => l.date === isoDate(d));
}
function heading() {
  panel.classList.toggle("day-mode", mode === "day");
  panel.classList.toggle("student-mode", userRole === "student");
  $("#student-role").setAttribute(
    "aria-pressed",
    String(userRole === "student"),
  );
  $("#teacher-role").setAttribute(
    "aria-pressed",
    String(userRole === "teacher"),
  );
  $("#student-class-control").hidden = userRole !== "student";
  $("#add-lesson").hidden = userRole !== "teacher";
  $("#add-lesson").disabled = !ready;
  $("#page-title").textContent =
    userRole === "student" ? "Розклад учня" : "Розклад викладача";
  $("#audience-description").textContent =
    userRole === "student"
      ? studentClass +
        " клас · " +
        (students.find((s) => s.id === studentId)?.name || "Обери профіль")
      : "Заняття, оцінки та коментарі учнів";
  const y =
    selectedDate.getMonth() >= 8
      ? selectedDate.getFullYear()
      : selectedDate.getFullYear() - 1;
  $("#academic-year").textContent = y + " / " + (y + 1) + " НАВЧАЛЬНИЙ РІК";
  $("#week-view").setAttribute("aria-pressed", String(mode === "week"));
  $("#day-view").setAttribute("aria-pressed", String(mode === "day"));
  $("#previous").setAttribute(
    "aria-label",
    mode === "week" ? "Попередній тиждень" : "Попередній день",
  );
  $("#next").setAttribute(
    "aria-label",
    mode === "week" ? "Наступний тиждень" : "Наступний день",
  );
}
function lessonCard(l) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = "lesson-card" + (l.online ? " online" : "");
  b.setAttribute(
    "aria-label",
    l.position +
      " урок. " +
      l.start_time +
      "–" +
      l.end_time +
      ". " +
      l.subject +
      ", " +
      l.class_name +
      ". " +
      l.topic +
      ". Відкрити заняття.",
  );
  b.innerHTML =
    '<span class="lesson-time"><span class="lesson-number">' +
    h(l.position) +
    "</span><span>" +
    h(l.start_time) +
    ' <span class="lesson-end">– ' +
    h(l.end_time) +
    '</span></span></span><span class="lesson-subject">' +
    h(l.subject) +
    '</span><span class="lesson-topic">' +
    h(l.topic) +
    '</span><span class="lesson-bottom"><span class="class-badge">' +
    h(l.class_name) +
    "</span>" +
    (l.online
      ? '<span class="online-badge">Онлайн</span>'
      : '<span class="room">' +
        (l.room ? "Каб. " + h(l.room) : "У школі") +
        "</span>") +
    "</span>";
  b.addEventListener("click", () => openLesson(l.id));
  return b;
}
function dayColumn(d) {
  const i = dayIndex(d),
    items = lessonsOn(d),
    column = document.createElement("section");
  column.className =
    "day-column" + (isoDate(d) === isoDate(selectedDate) ? " selected" : "");
  column.setAttribute("aria-label", weekdays[i] + ", " + fullDate(d));
  const title = document.createElement(mode === "week" ? "button" : "div");
  title.className = "day-header";
  if (mode === "week") {
    title.type = "button";
    title.setAttribute("aria-label", "Показати " + fullDate(d));
    title.addEventListener("click", () => {
      selectedDate = d;
      mode = "day";
      rememberView();
      render();
      $("#day-view").focus();
    });
  }
  title.innerHTML =
    '<span><span class="day-name">' +
    weekdays[i] +
    (isoDate(d) === isoDate(today) ? " · сьогодні" : "") +
    '</span><span class="day-date">' +
    lessonCountLabel(items.length) +
    '</span></span><time class="day-number" datetime="' +
    isoDate(d) +
    '">' +
    d.getDate() +
    "</time>";
  column.append(title);
  if (items.length) items.forEach((l) => column.append(lessonCard(l)));
  else {
    const empty = document.createElement("div");
    empty.className = "empty-day";
    empty.innerHTML =
      "<strong>Занять немає</strong><p>" +
      (userRole === "student"
        ? "Для твого класу цього дня занять не заплановано."
        : "Можна додати заняття на цей день.") +
      "</p>";
    column.append(empty);
  }
  if (userRole === "teacher") {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "add-day-button";
    b.textContent = "+ Заняття";
    b.setAttribute("aria-label", "Додати заняття на " + fullDate(d));
    b.addEventListener("click", () => openEditor(null, isoDate(d)));
    column.append(b);
  }
  return column;
}
function render() {
  heading();
  const days = [0, 1, 2, 3, 4];
  for (const i of [5, 6])
    if (lessonsOn(addDays(weekStart, i)).length) days.push(i);
  grid.classList.toggle("has-weekend", mode === "week" && days.length > 5);
  const end = addDays(weekStart, days.at(-1));
  $("#date-range").textContent =
    mode === "day"
      ? fullDate(selectedDate)
      : weekStart.getMonth() === end.getMonth()
        ? weekStart.getDate() +
          "–" +
          end.getDate() +
          " " +
          months[end.getMonth()] +
          " " +
          end.getFullYear()
        : weekStart.getDate() +
          " " +
          months[weekStart.getMonth()] +
          " — " +
          fullDate(end);
  grid.replaceChildren(
    ...(mode === "week"
      ? days.map((i) => dayColumn(addDays(weekStart, i)))
      : [dayColumn(selectedDate)]),
  );
  const strip = $("#day-strip");
  strip.replaceChildren();
  for (let i = 0; i < 7; i++) {
    const d = addDays(weekStart, i),
      b = document.createElement("button");
    b.type = "button";
    b.innerHTML = "<span>" + shortDays[i] + "</span><b>" + d.getDate() + "</b>";
    b.setAttribute("aria-label", weekdays[i] + ", " + fullDate(d));
    b.setAttribute(
      "aria-pressed",
      String(isoDate(d) === isoDate(selectedDate)),
    );
    b.addEventListener("click", () => {
      selectedDate = d;
      render();
      $("#day-strip").children[i].focus();
    });
    strip.append(b);
  }
  const n = mode === "week" ? lessons.length : lessonsOn(selectedDate).length;
  $("#lesson-count").textContent =
    lessonCountLabel(n) + (mode === "week" ? " на тиждень" : " на день");
  $("#schedule-announcement").textContent =
    $("#page-title").textContent +
    ". " +
    $("#date-range").textContent +
    ". " +
    lessonCountLabel(n) +
    ".";
}
async function loadWeek() {
  lessons = [];
  const token = ++weekRequest;
  heading();
  grid.inert = true;
  grid.replaceChildren();
  $("#connection-status").hidden = false;
  $("#connection-message").textContent = "Завантаження розкладу…";
  $("#retry-load").hidden = true;
  try {
    const r = await api("/api/week?start=" + isoDate(weekStart));
    if (token !== weekRequest) return;
    lessons = r.lessons;
    render();
    $("#connection-status").hidden = true;
  } catch (e) {
    if (token !== weekRequest) return;
    $("#connection-message").textContent = e.message;
    $("#retry-load").hidden = false;
  } finally {
    if (token === weekRequest) grid.inert = false;
  }
}
// Вікно заняття: оцінки, особисті записи та обговорення.
async function openLesson(id) {
  const token = ++detailRequest;
  activeDetails = null;
  $("#dialog-title").textContent = "Завантаження…";
  $("#dialog-topic").textContent = "";
  $("#dialog-date").textContent = "";
  $("#dialog-details").replaceChildren();
  $("#lesson-workspace").replaceChildren();
  $("#lesson-actions").hidden = true;
  $("#details-error").textContent = "";
  if (!dialog.open) dialog.showModal();
  try {
    const data = await api("/api/lesson?id=" + encodeURIComponent(id));
    if (token !== detailRequest || !dialog.open) return;
    activeDetails = data;
    renderDetails();
  } catch (e) {
    if (token === detailRequest) $("#details-error").textContent = e.message;
  }
}
function renderDetails() {
  const data = activeDetails,
    l = data.lesson;
  $("#dialog-title").textContent = l.subject;
  $("#dialog-topic").textContent = l.topic;
  $("#dialog-date").textContent =
    weekdays[dayIndex(parseDate(l.date))] + ", " + fullDate(parseDate(l.date));
  $("#dialog-details").innerHTML =
    "<dt>Урок</dt><dd>" +
    h(l.position) +
    "</dd><dt>Час</dt><dd>" +
    h(l.start_time) +
    "–" +
    h(l.end_time) +
    "</dd><dt>Клас</dt><dd>" +
    h(l.class_name) +
    "</dd><dt>Формат</dt><dd>" +
    (l.online ? "Онлайн" : "У школі" + (l.room ? " · каб. " + h(l.room) : "")) +
    "</dd>";
  $("#lesson-actions").hidden = userRole !== "teacher";
  const box = $("#lesson-workspace");
  if (userRole === "teacher") {
    box.innerHTML =
      '<section class="workspace-section"><h3>Оцінки учням</h3><p class="form-hint">Від 1 до 12. Порожнє поле прибирає оцінку.</p><form id="grades-form"><div class="grade-list">' +
      data.students
        .map((s) => {
          const g = data.grades.find((x) => x.student_id === s.id);
          return (
            '<div class="grade-row" data-student="' +
            h(s.id) +
            '"><strong>' +
            h(s.name) +
            '</strong><label><span class="sr-only">Оцінка для ' +
            h(s.name) +
            '</span><input name="grade" type="number" min="1" max="12" step="1" value="' +
            h(g?.grade ?? "") +
            '" placeholder="—"></label><label><span class="sr-only">Коментар до оцінки для ' +
            h(s.name) +
            '</span><input name="feedback" maxlength="1000" value="' +
            h(g?.feedback ?? "") +
            '" placeholder="Коментар до оцінки"></label></div>'
          );
        })
        .join("") +
      '</div><p class="form-error" role="alert"></p><button class="action-button" type="submit">Зберегти оцінки</button></form></section>';
    $("#grades-form").addEventListener("submit", (e) => {
      e.preventDefault();
      const form = e.currentTarget;
      void submitAction(form, form.querySelector(".form-error"), async () => {
        const grades = [...form.querySelectorAll(".grade-row")].map((row) => ({
          student_id: row.dataset.student,
          grade:
            row.querySelector('[name="grade"]').value === ""
              ? null
              : Number(row.querySelector('[name="grade"]').value),
          feedback: row.querySelector('[name="feedback"]').value,
        }));
        await api("/api/grades", "PUT", { lesson_id: l.id, grades });
        toast("Оцінки збережено");
      });
    });
  } else {
    const g = data.grades[0];
    box.innerHTML =
      '<section class="workspace-section"><h3>Моя оцінка</h3><div class="my-grade"><span>' +
      (g ? h(g.grade) + "<small> / 12</small>" : "Ще не виставлена") +
      "</span>" +
      (g?.feedback ? "<p>" + h(g.feedback) + "</p>" : "") +
      '</div></section><section class="workspace-section"><h3>Мій запис</h3><p class="form-hint">Особисті нотатки обраного профілю. Вони не публікуються в коментарях.</p><form id="note-form"><label class="sr-only" for="note-body">Особистий запис</label><textarea id="note-body" maxlength="5000" rows="4" placeholder="Що варто запам’ятати з уроку…">' +
      h(data.note) +
      '</textarea><p class="form-error" role="alert"></p><button class="action-button" type="submit">Зберегти запис</button></form></section>';
    $("#note-form").addEventListener("submit", (e) => {
      e.preventDefault();
      const form = e.currentTarget;
      void submitAction(form, form.querySelector(".form-error"), async () => {
        await api("/api/note", "PUT", {
          lesson_id: l.id,
          body: $("#note-body").value,
        });
        toast("Особистий запис збережено");
      });
    });
  }
  const section = document.createElement("section");
  section.className = "workspace-section";
  section.innerHTML =
    '<h3>Коментарі до заняття</h3><p class="form-hint">Їх бачать викладач і учні цього класу.</p><div id="comments-list"></div>' +
    (userRole === "student"
      ? '<form id="comment-form"><label class="sr-only" for="comment-body">Новий коментар</label><textarea id="comment-body" maxlength="2000" rows="3" required placeholder="Постав запитання або залиш коментар…"></textarea><p class="form-error" role="alert"></p><button class="action-button" type="submit">Додати коментар</button></form>'
      : "");
  box.append(section);
  renderComments();
  if (userRole === "student")
    $("#comment-form").addEventListener("submit", (e) => {
      e.preventDefault();
      const form = e.currentTarget;
      void submitAction(form, form.querySelector(".form-error"), async () => {
        await api("/api/comments", "POST", {
          lesson_id: l.id,
          body: $("#comment-body").value,
        });
        $("#comment-body").value = "";
        toast("Коментар додано");
        await reloadComments();
      });
    });
}
async function reloadComments() {
  const id = activeDetails?.lesson.id;
  if (!id) return;
  const d = await api("/api/lesson?id=" + encodeURIComponent(id));
  if (activeDetails?.lesson.id !== id || !dialog.open) return;
  activeDetails.comments = d.comments;
  renderComments();
}
function renderComments() {
  const list = $("#comments-list");
  list.replaceChildren();
  if (!activeDetails.comments.length) {
    list.innerHTML =
      '<p class="form-hint no-comments">Коментарів поки немає.</p>';
    return;
  }
  for (const c of activeDetails.comments) {
    const a = document.createElement("article");
    a.className = "comment";
    a.innerHTML =
      '<div class="comment-heading"><strong>' +
      h(c.author) +
      (c.own ? " · я" : "") +
      "</strong><time>" +
      h(
        new Date(c.created_at).toLocaleString("uk-UA", {
          timeZone: "Europe/Kyiv",
          day: "numeric",
          month: "short",
          hour: "2-digit",
          minute: "2-digit",
        }),
      ) +
      '</time></div><p class="comment-body">' +
      h(c.body) +
      "</p>" +
      (c.own
        ? '<div class="comment-actions"><button class="text-button edit-comment" type="button">Редагувати</button><button class="text-button delete-comment" type="button">Видалити</button></div>'
        : "") +
      '<p class="form-error" role="alert"></p>';
    if (c.own) {
      a.querySelector(".delete-comment").addEventListener(
        "click",
        async (e) => {
          const b = e.currentTarget;
          b.disabled = true;
          try {
            await api("/api/comment", "DELETE", { id: c.id });
            toast("Коментар видалено");
            await reloadComments();
          } catch (error) {
            a.querySelector(".form-error").textContent = error.message;
            b.disabled = false;
          }
        },
      );
      a.querySelector(".edit-comment").addEventListener("click", () => {
        if (a.querySelector("form")) return;
        const f = document.createElement("form");
        f.innerHTML =
          '<textarea maxlength="2000" required rows="3" aria-label="Текст коментаря">' +
          h(c.body) +
          '</textarea><p class="form-error" role="alert"></p><div class="comment-actions"><button type="submit" class="action-button">Зберегти</button><button type="button" class="text-button cancel-edit">Скасувати</button></div>';
        a.append(f);
        a.querySelector(".comment-actions").hidden = true;
        f.querySelector("textarea").focus();
        f.querySelector(".cancel-edit").addEventListener("click", () => {
          f.remove();
          a.querySelector(".comment-actions").hidden = false;
        });
        f.addEventListener("submit", (e) => {
          e.preventDefault();
          void submitAction(f, f.querySelector(".form-error"), async () => {
            await api("/api/comment", "PUT", {
              id: c.id,
              body: f.querySelector("textarea").value,
            });
            toast("Коментар змінено");
            await reloadComments();
          });
        });
      });
    }
    list.append(a);
  }
}
// Створення, редагування й видалення конкретного заняття.
function openEditor(l = null, date = isoDate(selectedDate)) {
  if (userRole !== "teacher" || !ready) return;
  editingLesson = l;
  $("#lesson-form").reset();
  $("#editor-error").textContent = "";
  $("#editor-title").textContent = l ? "Редагувати заняття" : "Додати заняття";
  fillSelect($("#lesson-class"), classes, l?.class_name || studentClass);
  $("#lesson-date").value = l?.date || date;
  $("#lesson-date").readOnly = Boolean(l);
  const dayLessons = lessons.filter((x) => x.date === date);
  $("#lesson-position").value =
    l?.position ||
    Math.min(20, Math.max(0, ...dayLessons.map((x) => x.position)) + 1);
  $("#lesson-start").value = l?.start_time || "14:30";
  $("#lesson-end").value = l?.end_time || "15:15";
  $("#lesson-room").value = l?.room || "";
  $("#lesson-subject").value = l?.subject || "Англійська мова";
  $("#lesson-topic").value = l?.topic || "";
  $("#lesson-online").checked = Boolean(l?.online);
  $("#lesson-room").disabled = $("#lesson-online").checked;
  $("#editor-dialog").showModal();
}
$("#lesson-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const form = e.currentTarget;
  void submitAction(form, $("#editor-error"), async () => {
    const body = {
      date: $("#lesson-date").value,
      class_name: $("#lesson-class").value,
      position: Number($("#lesson-position").value),
      subject: $("#lesson-subject").value,
      topic: $("#lesson-topic").value,
      start_time: $("#lesson-start").value,
      end_time: $("#lesson-end").value,
      room: $("#lesson-room").value,
      online: $("#lesson-online").checked,
    };
    if (editingLesson) {
      body.id = editingLesson.id;
      body.version = editingLesson.version;
    }
    const result = await api(
      editingLesson ? "/api/lesson" : "/api/lessons",
      editingLesson ? "PUT" : "POST",
      body,
    );
    $("#editor-dialog").close();
    selectedDate = parseDate(result.lesson.date);
    weekStart = mondayOf(selectedDate);
    toast(editingLesson ? "Заняття оновлено" : "Заняття додано");
    await loadWeek();
    await openLesson(result.lesson.id);
  });
});
$("#edit-lesson").addEventListener("click", () => {
  if (activeDetails) openEditor(activeDetails.lesson);
});
$("#delete-lesson").addEventListener("click", () => {
  if (!activeDetails) return;
  $("#delete-error").textContent = "";
  const l = activeDetails.lesson;
  $("#delete-summary").textContent =
    l.subject + ", " + l.class_name + " клас · " + fullDate(parseDate(l.date));
  $("#delete-dialog").showModal();
});
$("#confirm-delete").addEventListener("click", async (e) => {
  if (!activeDetails) return;
  const b = e.currentTarget;
  b.disabled = true;
  try {
    await api("/api/lesson", "DELETE", {
      id: activeDetails.lesson.id,
      version: activeDetails.lesson.version,
    });
    $("#delete-dialog").close();
    dialog.close();
    activeDetails = null;
    toast("Заняття видалено з цього дня");
    await loadWeek();
  } catch (error) {
    $("#delete-error").textContent = error.message;
  } finally {
    b.disabled = false;
  }
});
$("#cancel-delete").addEventListener("click", () =>
  $("#delete-dialog").close(),
);
$("#close-editor").addEventListener("click", () => $("#editor-dialog").close());
$("#lesson-online").addEventListener(
  "change",
  () => ($("#lesson-room").disabled = $("#lesson-online").checked),
);
$("#add-lesson").addEventListener("click", () => openEditor());
$("#close-dialog").addEventListener("click", () => dialog.close());
dialog.addEventListener("close", () => {
  detailRequest++;
  activeDetails = null;
});
// Навігація та профілі.
async function navigate(n) {
  selectedDate = addDays(selectedDate, n * (mode === "week" ? 7 : 1));
  weekStart = mondayOf(selectedDate);
  await loadWeek();
}
$("#previous").addEventListener("click", () => navigate(-1));
$("#next").addEventListener("click", () => navigate(1));
$("#today").addEventListener("click", () => {
  selectedDate = kyivToday();
  weekStart = mondayOf(selectedDate);
  if (dayIndex(selectedDate) > 4) mode = "day";
  void loadWeek();
});
for (const v of ["week", "day"])
  $("#" + v + "-view").addEventListener("click", () => {
    mode = v;
    rememberView();
    render();
  });
for (const r of ["teacher", "student"])
  $("#" + r + "-role").addEventListener("click", () => {
    userRole = r;
    rememberView();
    void loadWeek();
  });
$("#student-class").addEventListener("change", () => {
  studentClass = $("#student-class").value;
  fillProfiles();
  rememberView();
  void loadWeek();
});
$("#student-profile").addEventListener("change", () => {
  studentId = $("#student-profile").value;
  rememberView();
  void loadWeek();
});
$("#retry-load").addEventListener("click", () => {
  void (ready ? loadWeek() : initialize());
});
async function initialize() {
  $("#add-lesson").disabled = true;
  try {
    const d = await api("/api/bootstrap");
    classes = d.classes;
    students = d.students;
    if (!classes.includes(studentClass)) studentClass = classes[0] || "";
    restoreView();
    fillSelect($("#student-class"), classes, studentClass);
    fillProfiles();
    ready = true;
    await loadWeek();
  } catch (e) {
    $("#connection-status").hidden = false;
    $("#connection-message").textContent = e.message;
    $("#retry-load").hidden = false;
  }
}
void initialize();
