<script setup>
// 根组件只负责挂载路由；布局由各路由的 Layout 组件承担
</script>

<template>
  <router-view />
</template>

<style>
html, body, #app { height: 100%; margin: 0; }
body { font-family: "Helvetica Neue", Arial, "PingFang SC", "Microsoft YaHei", sans-serif; color: #1f2329; }
</style>
