<script setup>
defineProps({ user: Object })
</script>

<template>
  <header class="page-header">
    <div><p class="eyebrow">РОБОЧИЙ ПРОСТІР</p><h1>Вітаємо, {{ user?.first_name || user?.username }}</h1><p>Ваші інструменти залежать від ролі та наданих доступів.</p></div>
    <span class="status">● Local alpha</span>
  </header>
  <section class="cards">
    <article><small>ВАША РОЛЬ</small><strong>{{ user?.role || '...' }}</strong><p>Інтерфейс і API обмежуються роллю користувача.</p></article>
    <article v-if="user?.role === 'admin'"><small>КЕРУВАННЯ</small><strong>Працівники</strong><p>Створення, редагування та деактивація акаунтів команди.</p><RouterLink to="/employees">Відкрити →</RouterLink></article>
    <article v-if="user?.role === 'admin'"><small>НОВІ ЗВЕРНЕННЯ</small><strong>Пул клієнтів</strong><p>Призначайте самостійно зареєстрованих клієнтів працівникам.</p><RouterLink to="/unassigned">Відкрити →</RouterLink></article>
    <article v-if="user?.role === 'employee'"><small>РОБОЧА БАЗА</small><strong>Клієнти</strong><p>Переглядайте й редагуйте лише доступні вам анкети.</p><RouterLink to="/clients">Відкрити →</RouterLink></article>
    <article v-if="user?.role === 'client'"><small>ОСОБИСТИЙ КАБІНЕТ</small><strong>Моя анкета</strong><p>Контакти відповідальних працівників і поточний стан проєкту.</p><RouterLink to="/my-account">Відкрити →</RouterLink></article>
  </section>
</template>
