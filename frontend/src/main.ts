import { createApp } from "vue";
import { createRouter, createWebHistory } from "vue-router";
import App from "./App.vue";
import "./style.css";
import "./forms.css";

const router = createRouter({
  history: createWebHistory("/tracecore"),
  routes: [{ path: "/:pathMatch(.*)*", component: { template: "<span />" } }],
});
createApp(App).use(router).mount("#app");
