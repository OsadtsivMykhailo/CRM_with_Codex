<template>
  <header class="page-header"><div><p class="eyebrow">КОРПОРАТИВНА ПОШТА</p><h1>Email-налаштування</h1><p>Оберіть функціонал, який потрібно налаштувати.</p></div></header>
  <section class="cards group-cards">
    <RouterLink class="panel clickable" to="/email-settings/smtp"><h2>SMTP-сервер</h2><p>Підключення до поштового сервера та назва компанії-відправника.</p></RouterLink>
    <RouterLink class="panel clickable" to="/email-settings/senders"><h2>Загальні адреси</h2><p>Корпоративні адреси та працівники, яким дозволено їх використовувати.</p></RouterLink>
    <RouterLink class="panel clickable" to="/email-settings/templates"><h2>Спільні шаблони</h2><p>Шаблони листів, доступні всім працівникам.</p></RouterLink>
  </section>
</template>
