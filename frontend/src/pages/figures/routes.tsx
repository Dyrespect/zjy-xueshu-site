import type { RouteObject } from "react-router";

import { lazyPage } from "@/lib/lazy-page";

import GalleryLayout from "./GalleryLayout";
import HomePage from "./HomePage";

// 首页跟外框一起进首屏包；结果、按图型浏览、详情点进去才下载
const SearchPage = lazyPage(() => import("./SearchPage"));
const BrowsePage = lazyPage(() => import("./BrowsePage"));
const DetailPage = lazyPage(() => import("./DetailPage"));
const RequestPage = lazyPage(() => import("./RequestPage"));
const SubmitPage = lazyPage(() => import("./SubmitPage"));
const PluginPage = lazyPage(() => import("./PluginPage"));
const CopyrightPage = lazyPage(() => import("./CopyrightPage"));

/** 图库网站：首页、搜索结果、按图型浏览、图详情、提需求、投图、插件、版权问题（App.tsx 自动收集，不用改它） */
const routes: RouteObject[] = [
  {
    element: <GalleryLayout />,
    children: [
      // 11-18 站点整合：站点根 / 给官网首页，图库首页挪到 /tuku（图库其余各页地址不变）
      { path: "/tuku", element: <HomePage /> },
      { path: "/search", element: <SearchPage /> },
      { path: "/types/:code", element: <BrowsePage /> },
      { path: "/figure/:id", element: <DetailPage /> },
      // 统一站点（模块 L）：页头「提需求」「投图」，页脚「把图库装进你的 AI」「版权问题」
      { path: "/request", element: <RequestPage /> },
      { path: "/submit", element: <SubmitPage /> },
      { path: "/plugin", element: <PluginPage /> },
      { path: "/copyright", element: <CopyrightPage /> },
    ],
  },
];

export default routes;
