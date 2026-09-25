(function() {
	//#region src/scene/prefabs.ts
	/** 白模色板：整体偏白，只用色相区分类别，好认不抢戏。 */
	const C = {
		wall: "#eceef1",
		wall2: "#dfe3e8",
		roof: "#c3c9d1",
		roofDark: "#8f97a3",
		dark: "#6b727d",
		glass: "#a9bccd",
		wood: "#cdb99e",
		woodDark: "#9b8468",
		metal: "#b8bec6",
		foliage: "#a3b8a6",
		foliageDark: "#86a08d",
		trunk: "#a8927c",
		water: "#a9c0d3",
		red: "#d65a55",
		blue: "#3f6fd8",
		yellow: "#e6c34a",
		orange: "#e8894a",
		white: "#f7f7f8",
		black: "#40444b",
		light: "#fff4d6"
	};
	const n = (v, d) => typeof v === "number" && Number.isFinite(v) ? v : d;
	const s = (v, d) => typeof v === "string" && v ? v : d;
	const b = (v, d) => typeof v === "boolean" ? v : d;
	const box = (size, pos, color, rot) => ({
		prim: "box",
		size,
		pos,
		color,
		rot
	});
	const cyl = (d, h, pos, color, rot, segments = 10) => ({
		prim: "cylinder",
		size: [
			d,
			h,
			d
		],
		pos,
		color,
		rot,
		segments
	});
	const cone = (d, h, pos, color, segments = 8, rot) => ({
		prim: "cone",
		size: [
			d,
			h,
			d
		],
		pos,
		color,
		segments,
		rot
	});
	const ball = (size, pos, color, segments = 8) => ({
		prim: "sphere",
		size,
		pos,
		color,
		segments
	});
	/** 三角棱柱：三角形在 XY 面（底宽 size[0]、高 size[1]），沿 Z 拉伸 size[2]。 */
	const prism = (size, pos, color, rot) => ({
		prim: "prism",
		size,
		pos,
		color,
		rot
	});
	/** 四坡屋顶：底面是 w×d 的矩形的四棱锥。 */
	const pyramid = (w, h, d, pos, color) => ({
		prim: "cone",
		size: [
			w * Math.SQRT2,
			h,
			d * Math.SQRT2
		],
		pos,
		color,
		segments: 4,
		arc: [45, 360]
	});
	const wheel = (d, w, pos) => cyl(d, w, pos, C.black, [
		0,
		0,
		90
	], 12);
	/** 双坡屋顶：屋脊沿 X（面阔方向），前后两坡。 */
	function gable(w, d, h, y, color, over = .5) {
		return [prism([
			d + over * 2,
			h,
			w + over * 2
		], [
			0,
			y + h / 2,
			0
		], color, [
			0,
			90,
			0
		])];
	}
	const PREFABS = {
		house: {
			zh: "民居",
			category: "建筑",
			doc: "一栋房子，正门朝 +Z。宽 width（沿 X）× 深 depth（沿 Z），每层 3m",
			params: {
				width: {
					default: 6,
					doc: "面阔（米）"
				},
				depth: {
					default: 5,
					doc: "进深（米）"
				},
				floors: {
					default: 1,
					doc: "层数"
				},
				roof: {
					default: "gable",
					doc: "屋顶",
					options: [
						"gable",
						"hip",
						"flat"
					]
				},
				style: {
					default: "modern",
					doc: "风格",
					options: ["modern", "ancient"]
				}
			},
			build: (p) => {
				const w = n(p.width, 6), d = n(p.depth, 5), f = Math.max(1, Math.round(n(p.floors, 1)));
				const ancient = s(p.style, "modern") === "ancient";
				const H = 3 * f;
				const parts = [];
				if (ancient) parts.push(box([
					w + .8,
					.35,
					d + .8
				], [
					0,
					.175,
					0
				], C.roof));
				const y0 = ancient ? .35 : 0;
				parts.push(box([
					w,
					H,
					d
				], [
					0,
					y0 + H / 2,
					0
				], C.wall));
				const roof = s(p.roof, "gable");
				if (roof === "flat") parts.push(box([
					w + .3,
					.3,
					d + .3
				], [
					0,
					y0 + H + .15,
					0
				], C.roof));
				else if (roof === "hip") parts.push(pyramid(w + (ancient ? 1.6 : .6), ancient ? 2.2 : 1.6, d + (ancient ? 1.6 : .6), [
					0,
					y0 + H + (ancient ? 1.1 : .8),
					0
				], ancient ? C.roofDark : C.roof));
				else parts.push(...gable(w, d, ancient ? 2 : 1.5, y0 + H, ancient ? C.roofDark : C.roof, ancient ? .9 : .4));
				if (ancient && roof !== "flat") parts.push(box([
					w + 1.8,
					.22,
					.3
				], [
					0,
					y0 + H + 2,
					0
				], C.dark));
				parts.push(box([
					1.1,
					2.1,
					.08
				], [
					0,
					y0 + 1.05,
					d / 2 + .04
				], C.woodDark));
				for (let i = 0; i < f; i++) for (const x of [-w * .3, w * .3]) parts.push(box([
					.95,
					.95,
					.06
				], [
					x,
					y0 + 1.7 + 3 * i,
					d / 2 + .03
				], ancient ? C.wood : C.glass));
				if (ancient) for (const x of [-w / 2 + .2, w / 2 - .2]) parts.push(cyl(.28, H, [
					x,
					y0 + H / 2,
					d / 2 + .35
				], C.woodDark));
				return parts;
			}
		},
		building: {
			zh: "楼房",
			category: "建筑",
			doc: "多层楼，正面朝 +Z，每层 3.2m，有横向窗带",
			params: {
				width: {
					default: 10,
					doc: "宽（米）"
				},
				depth: {
					default: 10,
					doc: "深（米）"
				},
				floors: {
					default: 6,
					doc: "层数"
				}
			},
			build: (p) => {
				const w = n(p.width, 10), d = n(p.depth, 10), f = Math.max(1, Math.round(n(p.floors, 6)));
				const H = 3.2 * f;
				const parts = [box([
					w,
					H,
					d
				], [
					0,
					H / 2,
					0
				], C.wall2), box([
					w + .3,
					.5,
					d + .3
				], [
					0,
					H + .25,
					0
				], C.roof)];
				for (let i = 0; i < f; i++) {
					const y = 3.2 * i + 1.8;
					parts.push(box([
						w * .9,
						1.1,
						.06
					], [
						0,
						y,
						d / 2 + .03
					], C.glass), box([
						w * .9,
						1.1,
						.06
					], [
						0,
						y,
						-d / 2 - .03
					], C.glass));
					parts.push(box([
						.06,
						1.1,
						d * .9
					], [
						w / 2 + .03,
						y,
						0
					], C.glass), box([
						.06,
						1.1,
						d * .9
					], [
						-w / 2 - .03,
						y,
						0
					], C.glass));
				}
				parts.push(box([
					2.2,
					2.6,
					.1
				], [
					0,
					1.3,
					d / 2 + .05
				], C.dark));
				return parts;
			}
		},
		skyscraper: {
			zh: "摩天楼",
			category: "建筑",
			doc: "高层塔楼（默认 30 层约 100m），竖向窗条",
			params: {
				width: {
					default: 16,
					doc: "宽"
				},
				depth: {
					default: 16,
					doc: "深"
				},
				floors: {
					default: 30,
					doc: "层数"
				}
			},
			build: (p) => {
				const w = n(p.width, 16), d = n(p.depth, 16), H = 3.3 * Math.max(5, n(p.floors, 30));
				const parts = [
					box([
						w,
						H,
						d
					], [
						0,
						H / 2,
						0
					], C.wall2),
					box([
						w * .7,
						4,
						d * .7
					], [
						0,
						H + 2,
						0
					], C.roof),
					cyl(.3, 12, [
						0,
						H + 10,
						0
					], C.metal)
				];
				for (let i = 0; i < 5; i++) {
					const t = -w / 2 + w / 5 * (i + .5);
					parts.push(box([
						w / 10,
						H * .96,
						.1
					], [
						t,
						H / 2,
						d / 2 + .05
					], C.glass), box([
						w / 10,
						H * .96,
						.1
					], [
						t,
						H / 2,
						-d / 2 - .05
					], C.glass));
					const z = -d / 2 + d / 5 * (i + .5);
					parts.push(box([
						.1,
						H * .96,
						d / 10
					], [
						w / 2 + .05,
						H / 2,
						z
					], C.glass), box([
						.1,
						H * .96,
						d / 10
					], [
						-w / 2 - .05,
						H / 2,
						z
					], C.glass));
				}
				return parts;
			}
		},
		shop: {
			zh: "商铺",
			category: "建筑",
			doc: "临街小店：一层、平顶、门前遮阳篷和招牌，门朝 +Z",
			params: {
				width: {
					default: 6,
					doc: "宽"
				},
				depth: {
					default: 6,
					doc: "深"
				},
				color: {
					default: "#d65a55",
					doc: "遮阳篷颜色"
				}
			},
			build: (p) => {
				const w = n(p.width, 6), d = n(p.depth, 6);
				return [
					box([
						w,
						3.6,
						d
					], [
						0,
						1.8,
						0
					], C.wall),
					box([
						w + .2,
						.3,
						d + .2
					], [
						0,
						3.75,
						0
					], C.roof),
					box([
						w * .8,
						2.4,
						.06
					], [
						0,
						1.4,
						d / 2 + .03
					], C.glass),
					box([
						w,
						.08,
						1.5
					], [
						0,
						2.95,
						d / 2 + .7
					], s(p.color, C.red), [
						-14,
						0,
						0
					]),
					box([
						w * .8,
						.6,
						.12
					], [
						0,
						3.35,
						d / 2 + .06
					], C.dark)
				];
			}
		},
		pagoda: {
			zh: "塔",
			category: "建筑",
			doc: "多层古塔，每层一圈四坡檐",
			params: {
				tiers: {
					default: 5,
					doc: "层数"
				},
				width: {
					default: 7,
					doc: "底层宽"
				}
			},
			build: (p) => {
				const t = Math.max(1, Math.round(n(p.tiers, 5))), w0 = n(p.width, 7);
				const parts = [box([
					w0 + 2,
					.6,
					w0 + 2
				], [
					0,
					.3,
					0
				], C.roof)];
				let y = .6;
				for (let i = 0; i < t; i++) {
					const w = w0 * (1 - i * .12), h = i === 0 ? 3.4 : 2.6;
					parts.push(box([
						w,
						h,
						w
					], [
						0,
						y + h / 2,
						0
					], C.wall));
					parts.push(pyramid(w + 2, 1.2, w + 2, [
						0,
						y + h + .3,
						0
					], C.roofDark));
					y += h + .6;
				}
				parts.push(cone(.5, 3, [
					0,
					y + 1.5,
					0
				], C.dark, 6));
				return parts;
			}
		},
		pavilion: {
			zh: "亭子",
			category: "建筑",
			doc: "四柱攒尖亭，四面通透",
			params: { width: {
				default: 4,
				doc: "宽"
			} },
			build: (p) => {
				const w = n(p.width, 4);
				const parts = [box([
					w + .8,
					.4,
					w + .8
				], [
					0,
					.2,
					0
				], C.roof)];
				for (const x of [-w / 2, w / 2]) for (const z of [-w / 2, w / 2]) parts.push(cyl(.26, 3, [
					x,
					1.9,
					z
				], C.woodDark));
				parts.push(pyramid(w + 1.6, 1.8, w + 1.6, [
					0,
					4.3,
					0
				], C.roofDark), ball([
					.4,
					.4,
					.4
				], [
					0,
					5.3,
					0
				], C.dark));
				return parts;
			}
		},
		gate: {
			zh: "牌坊",
			category: "建筑",
			doc: "门楼/牌坊：两柱一楣一顶，门洞朝 Z 方向可穿过",
			params: {
				width: {
					default: 6,
					doc: "宽"
				},
				height: {
					default: 5,
					doc: "高"
				}
			},
			build: (p) => {
				const w = n(p.width, 6), h = n(p.height, 5);
				return [
					cyl(.45, h, [
						-w / 2,
						h / 2,
						0
					], C.woodDark),
					cyl(.45, h, [
						w / 2,
						h / 2,
						0
					], C.woodDark),
					box([
						w + 1,
						.5,
						.5
					], [
						0,
						h - .6,
						0
					], C.red),
					box([
						w * .6,
						.8,
						.2
					], [
						0,
						h - 1.5,
						0
					], C.dark),
					...gable(w + .6, 1, .9, h - .3, C.roofDark, .5)
				];
			}
		},
		wall: {
			zh: "墙",
			category: "建筑",
			doc: "一段墙，沿 X 方向延伸 length 米",
			params: {
				length: {
					default: 6,
					doc: "长"
				},
				height: {
					default: 2.5,
					doc: "高"
				},
				thickness: {
					default: .3,
					doc: "厚"
				},
				style: {
					default: "modern",
					doc: "风格（ancient 带瓦顶）",
					options: ["modern", "ancient"]
				}
			},
			build: (p) => {
				const l = n(p.length, 6), h = n(p.height, 2.5), t = n(p.thickness, .3);
				const parts = [box([
					l,
					h,
					t
				], [
					0,
					h / 2,
					0
				], C.wall2)];
				if (s(p.style, "modern") === "ancient") parts.push(prism([
					t + .5,
					.4,
					l + .2
				], [
					0,
					h + .2,
					0
				], C.roofDark, [
					0,
					90,
					0
				]));
				return parts;
			}
		},
		fence: {
			zh: "栅栏",
			category: "建筑",
			doc: "栅栏，沿 X 方向延伸 length 米",
			params: {
				length: {
					default: 6,
					doc: "长"
				},
				height: {
					default: 1,
					doc: "高"
				}
			},
			build: (p) => {
				const l = n(p.length, 6), h = n(p.height, 1);
				const parts = [];
				const k = Math.max(2, Math.round(l / 1.5) + 1);
				for (let i = 0; i < k; i++) parts.push(box([
					.1,
					h,
					.1
				], [
					-l / 2 + l / (k - 1) * i,
					h / 2,
					0
				], C.wood));
				parts.push(box([
					l,
					.08,
					.05
				], [
					0,
					h * .8,
					0
				], C.wood), box([
					l,
					.08,
					.05
				], [
					0,
					h * .35,
					0
				], C.wood));
				return parts;
			}
		},
		bridge: {
			zh: "桥",
			category: "建筑",
			doc: "桥，桥身沿 X 方向（左右）跨越 span 米；arch=true 是拱桥",
			params: {
				span: {
					default: 12,
					doc: "跨度"
				},
				width: {
					default: 4,
					doc: "桥面宽"
				},
				arch: {
					default: true,
					doc: "拱桥"
				},
				rise: {
					default: 2.2,
					doc: "拱高"
				}
			},
			build: (p) => {
				const L = n(p.span, 12), W = n(p.width, 4), arch = b(p.arch, true), rise = arch ? n(p.rise, 2.2) : 0;
				const parts = [];
				const seg = arch ? 10 : 1;
				for (let i = 0; i < seg; i++) {
					const u0 = i / seg, u1 = (i + 1) / seg;
					const x0 = -L / 2 + L * u0, x1 = -L / 2 + L * u1;
					const y0 = rise * Math.sin(Math.PI * u0) + .6, y1 = rise * Math.sin(Math.PI * u1) + .6;
					const ang = Math.atan2(y1 - y0, x1 - x0) * 180 / Math.PI;
					const lenSeg = Math.hypot(x1 - x0, y1 - y0);
					const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
					parts.push(box([
						lenSeg + .05,
						.35,
						W
					], [
						cx,
						cy,
						0
					], C.roof, [
						0,
						0,
						ang
					]));
					for (const z of [-W / 2, W / 2]) parts.push(box([
						lenSeg + .05,
						.7,
						.15
					], [
						cx,
						cy + .5,
						z
					], C.wall2, [
						0,
						0,
						ang
					]));
				}
				if (!arch) for (const x of [-L / 2 + .5, L / 2 - .5]) parts.push(box([
					.6,
					.6,
					W
				], [
					x,
					.3,
					0
				], C.roof));
				return parts;
			}
		},
		stairs: {
			zh: "台阶",
			category: "建筑",
			doc: "台阶，从 +Z 一侧往 -Z 升高",
			params: {
				steps: {
					default: 8,
					doc: "级数"
				},
				width: {
					default: 3,
					doc: "宽"
				},
				rise: {
					default: .18,
					doc: "每级高"
				},
				run: {
					default: .3,
					doc: "每级深"
				}
			},
			build: (p) => {
				const k = Math.max(1, Math.round(n(p.steps, 8))), w = n(p.width, 3), r = n(p.rise, .18), d = n(p.run, .3);
				const parts = [];
				for (let i = 0; i < k; i++) parts.push(box([
					w,
					r * (i + 1),
					d
				], [
					0,
					r * (i + 1) / 2,
					(k / 2 - i - .5) * d
				], C.roof));
				return parts;
			}
		},
		column: {
			zh: "柱子",
			category: "建筑",
			doc: "圆柱",
			params: {
				height: {
					default: 4,
					doc: "高"
				},
				radius: {
					default: .3,
					doc: "半径"
				}
			},
			build: (p) => [cyl(n(p.radius, .3) * 2, n(p.height, 4), [
				0,
				n(p.height, 4) / 2,
				0
			], C.wall2, void 0, 14)]
		},
		stall: {
			zh: "摊位",
			category: "建筑",
			doc: "集市摊位：桌台、四根杆、顶棚，摊主一侧在 -Z",
			params: {
				width: {
					default: 2.6,
					doc: "宽"
				},
				color: {
					default: "#e8894a",
					doc: "顶棚颜色"
				}
			},
			build: (p) => {
				const w = n(p.width, 2.6);
				const parts = [box([
					w,
					.9,
					1.1
				], [
					0,
					.45,
					0
				], C.wood)];
				for (const x of [-w / 2, w / 2]) for (const z of [-.6, .6]) parts.push(cyl(.08, 2.4, [
					x,
					1.2,
					z
				], C.woodDark, void 0, 6));
				parts.push(box([
					w + .4,
					.1,
					1.8
				], [
					0,
					2.45,
					0
				], s(p.color, C.orange), [
					-8,
					0,
					0
				]));
				return parts;
			}
		},
		well: {
			zh: "水井",
			category: "建筑",
			doc: "带辘轳架的井",
			build: () => [
				cyl(1.4, .8, [
					0,
					.4,
					0
				], C.roof, void 0, 12),
				cyl(1.1, .82, [
					0,
					.42,
					0
				], C.dark, void 0, 12),
				box([
					.12,
					2,
					.12
				], [
					-.8,
					1,
					0
				], C.woodDark),
				box([
					.12,
					2,
					.12
				], [
					.8,
					1,
					0
				], C.woodDark),
				box([
					1.8,
					.12,
					.12
				], [
					0,
					1.9,
					0
				], C.woodDark),
				...gable(1.9, 1.2, .5, 2, C.roofDark, .1)
			]
		},
		streetlamp: {
			zh: "路灯",
			category: "街道",
			doc: "路灯，灯头伸向 +Z",
			params: {
				height: {
					default: 4.5,
					doc: "高"
				},
				style: {
					default: "modern",
					doc: "风格",
					options: ["modern", "ancient"]
				}
			},
			build: (p) => {
				const h = n(p.height, 4.5);
				if (s(p.style, "modern") === "ancient") return [
					box([
						.18,
						h,
						.18
					], [
						0,
						h / 2,
						0
					], C.woodDark),
					box([
						.12,
						.12,
						.8
					], [
						0,
						h - .2,
						.35
					], C.woodDark),
					{
						...ball([
							.45,
							.6,
							.45
						], [
							0,
							h - .6,
							.7
						], C.red),
						glow: true
					}
				];
				return [
					cyl(.16, h, [
						0,
						h / 2,
						0
					], C.metal, void 0, 8),
					box([
						.1,
						.1,
						1.2
					], [
						0,
						h,
						.55
					], C.metal),
					{
						...box([
							.4,
							.12,
							.5
						], [
							0,
							h - .08,
							1.05
						], C.light),
						glow: true
					}
				];
			}
		},
		traffic_light: {
			zh: "红绿灯",
			category: "街道",
			doc: "红绿灯，灯面朝 +Z",
			build: () => [
				cyl(.16, 3.2, [
					0,
					1.6,
					0
				], C.dark, void 0, 8),
				box([
					.45,
					1.2,
					.35
				], [
					0,
					3.6,
					0
				], C.black),
				{
					...ball([
						.26,
						.26,
						.1
					], [
						0,
						4,
						.18
					], C.red),
					glow: true
				},
				ball([
					.26,
					.26,
					.1
				], [
					0,
					3.6,
					.18
				], C.yellow),
				ball([
					.26,
					.26,
					.1
				], [
					0,
					3.2,
					.18
				], "#4caf50")
			]
		},
		bench: {
			zh: "长椅",
			category: "街道",
			doc: "长椅，坐的人面朝 +Z",
			params: { length: {
				default: 1.8,
				doc: "长"
			} },
			build: (p) => {
				const l = n(p.length, 1.8);
				return [
					box([
						l,
						.08,
						.45
					], [
						0,
						.45,
						0
					], C.wood),
					box([
						l,
						.45,
						.06
					], [
						0,
						.72,
						-.22
					], C.wood, [
						-10,
						0,
						0
					]),
					box([
						.08,
						.45,
						.45
					], [
						-l / 2 + .1,
						.22,
						0
					], C.dark),
					box([
						.08,
						.45,
						.45
					], [
						l / 2 - .1,
						.22,
						0
					], C.dark)
				];
			}
		},
		trash_bin: {
			zh: "垃圾桶",
			category: "街道",
			doc: "垃圾桶",
			build: () => [cyl(.5, .9, [
				0,
				.45,
				0
			], C.dark, void 0, 10), cyl(.54, .06, [
				0,
				.92,
				0
			], C.black, void 0, 10)]
		},
		sign: {
			zh: "指示牌",
			category: "街道",
			doc: "立杆指示牌，牌面朝 +Z",
			build: () => [cyl(.08, 2.6, [
				0,
				1.3,
				0
			], C.metal, void 0, 6), box([
				1,
				.6,
				.06
			], [
				0,
				2.4,
				.05
			], C.blue)]
		},
		barrier: {
			zh: "路障",
			category: "街道",
			doc: "水马路障，沿 X 方向 2m",
			build: () => [box([
				2,
				.8,
				.45
			], [
				0,
				.4,
				0
			], C.orange), box([
				2.02,
				.18,
				.47
			], [
				0,
				.55,
				0
			], C.white)]
		},
		traffic_cone: {
			zh: "锥桶",
			category: "街道",
			doc: "交通锥",
			build: () => [box([
				.4,
				.04,
				.4
			], [
				0,
				.02,
				0
			], C.black), cone(.34, .7, [
				0,
				.39,
				0
			], C.orange, 10)]
		},
		hydrant: {
			zh: "消防栓",
			category: "街道",
			doc: "消防栓",
			build: () => [cyl(.28, .6, [
				0,
				.3,
				0
			], C.red, void 0, 8), ball([
				.28,
				.2,
				.28
			], [
				0,
				.65,
				0
			], C.red)]
		},
		bus_stop: {
			zh: "公交站",
			category: "街道",
			doc: "公交候车亭，候车一侧朝 +Z",
			build: () => [
				box([
					4,
					.12,
					1.6
				], [
					0,
					2.6,
					0
				], C.roof),
				box([
					4,
					2.3,
					.06
				], [
					0,
					1.3,
					-.75
				], C.glass),
				cyl(.1, 2.6, [
					-1.9,
					1.3,
					-.7
				], C.metal, void 0, 6),
				cyl(.1, 2.6, [
					1.9,
					1.3,
					-.7
				], C.metal, void 0, 6),
				box([
					3,
					.08,
					.4
				], [
					0,
					.45,
					-.5
				], C.wood)
			]
		},
		car: {
			zh: "轿车",
			category: "交通",
			doc: "轿车，车头朝 +Z（yaw 0 时往 +Z 开），长 4.5m",
			params: { color: {
				default: "#b8bec6",
				doc: "车身颜色"
			} },
			build: (p) => carParts(s(p.color, C.metal))
		},
		police_car: {
			zh: "警车",
			category: "交通",
			doc: "警车（白蓝涂装＋警灯），车头朝 +Z",
			build: () => [
				...carParts(C.white),
				box([
					1.84,
					.22,
					2.2
				], [
					0,
					.62,
					.1
				], C.blue),
				{
					...box([
						.45,
						.16,
						.32
					], [
						-.24,
						1.53,
						-.2
					], C.red),
					glow: true
				},
				{
					...box([
						.45,
						.16,
						.32
					], [
						.24,
						1.53,
						-.2
					], C.blue),
					glow: true
				}
			]
		},
		truck: {
			zh: "货车",
			category: "交通",
			doc: "厢式货车，车头朝 +Z，长约 8m",
			params: { color: {
				default: "#e2e5e9",
				doc: "货厢颜色"
			} },
			build: (p) => [
				box([
					2.3,
					2.2,
					2.1
				], [
					0,
					1.6,
					2.7
				], C.blue),
				box([
					2.1,
					.9,
					.05
				], [
					0,
					2.1,
					3.76
				], C.glass),
				box([
					2.45,
					2.9,
					5.4
				], [
					0,
					2.05,
					-1.2
				], s(p.color, C.wall2)),
				box([
					2.2,
					.4,
					7.8
				], [
					0,
					.55,
					.3
				], C.dark),
				wheel(1, .4, [
					-1.05,
					.5,
					2.6
				]),
				wheel(1, .4, [
					1.05,
					.5,
					2.6
				]),
				wheel(1, .4, [
					-1.05,
					.5,
					-2.2
				]),
				wheel(1, .4, [
					1.05,
					.5,
					-2.2
				]),
				wheel(1, .4, [
					-1.05,
					.5,
					-3.3
				]),
				wheel(1, .4, [
					1.05,
					.5,
					-3.3
				])
			]
		},
		bus: {
			zh: "公交车",
			category: "交通",
			doc: "公交车，车头朝 +Z，长 11m",
			params: { color: {
				default: "#3f9d6b",
				doc: "车身颜色"
			} },
			build: (p) => [
				box([
					2.5,
					2.9,
					11
				], [
					0,
					1.85,
					0
				], s(p.color, "#3f9d6b")),
				box([
					2.52,
					1,
					10.2
				], [
					0,
					2.35,
					-.2
				], C.glass),
				box([
					2.3,
					1.3,
					.05
				], [
					0,
					2.2,
					5.51
				], C.glass),
				wheel(1, .35, [
					-1.1,
					.5,
					3.6
				]),
				wheel(1, .35, [
					1.1,
					.5,
					3.6
				]),
				wheel(1, .35, [
					-1.1,
					.5,
					-3.4
				]),
				wheel(1, .35, [
					1.1,
					.5,
					-3.4
				])
			]
		},
		motorcycle: {
			zh: "摩托车",
			category: "交通",
			doc: "摩托车，车头朝 +Z",
			params: { color: {
				default: "#d65a55",
				doc: "颜色"
			} },
			build: (p) => [
				box([
					.34,
					.45,
					1.2
				], [
					0,
					.75,
					0
				], s(p.color, C.red)),
				box([
					.3,
					.1,
					.6
				], [
					0,
					1.02,
					-.2
				], C.black),
				box([
					.7,
					.05,
					.05
				], [
					0,
					1.08,
					.55
				], C.metal),
				wheel(.64, .14, [
					0,
					.32,
					.72
				]),
				wheel(.64, .14, [
					0,
					.32,
					-.72
				])
			]
		},
		bicycle: {
			zh: "自行车",
			category: "交通",
			doc: "自行车，车头朝 +Z",
			build: () => [
				{
					prim: "torus",
					size: [
						.68,
						.05,
						.68
					],
					pos: [
						0,
						.34,
						.52
					],
					rot: [
						0,
						90,
						0
					],
					color: C.black,
					segments: 16
				},
				{
					prim: "torus",
					size: [
						.68,
						.05,
						.68
					],
					pos: [
						0,
						.34,
						-.52
					],
					rot: [
						0,
						90,
						0
					],
					color: C.black,
					segments: 16
				},
				box([
					.05,
					.05,
					1
				], [
					0,
					.62,
					0
				], C.red, [
					20,
					0,
					0
				]),
				box([
					.05,
					.55,
					.05
				], [
					0,
					.6,
					-.2
				], C.red),
				box([
					.2,
					.05,
					.25
				], [
					0,
					.9,
					-.22
				], C.black),
				box([
					.55,
					.04,
					.04
				], [
					0,
					.98,
					.45
				], C.metal)
			]
		},
		boat: {
			zh: "船",
			category: "交通",
			doc: "小船，船头朝 +Z。style=canopy 是带篷的乌篷船",
			params: {
				length: {
					default: 6,
					doc: "长"
				},
				style: {
					default: "canopy",
					doc: "样式",
					options: ["rowboat", "canopy"]
				}
			},
			build: (p) => {
				const L = n(p.length, 6);
				const parts = [box([
					1.6,
					.6,
					L * .75
				], [
					0,
					.3,
					-L * .075
				], C.wood), prism([
					1.6,
					L * .25,
					.6
				], [
					0,
					.3,
					L * .425
				], C.wood, [
					90,
					0,
					0
				])];
				if (s(p.style, "canopy") === "canopy") parts.push({
					prim: "cylinder",
					size: [
						1.5,
						L * .4,
						1.5
					],
					pos: [
						0,
						.6,
						-L * .05
					],
					rot: [
						90,
						0,
						0
					],
					color: C.dark,
					segments: 10,
					arc: [90, 180]
				});
				return parts;
			}
		},
		helicopter: {
			zh: "直升机",
			category: "交通",
			doc: "直升机，机头朝 +Z",
			build: () => [
				ball([
					1.8,
					1.7,
					3.4
				], [
					0,
					1.6,
					.4
				], C.dark),
				box([
					.3,
					.4,
					3.6
				], [
					0,
					1.9,
					-2.6
				], C.dark),
				box([
					.08,
					.06,
					9
				], [
					0,
					2.65,
					.3
				], C.black),
				box([
					9,
					.06,
					.08
				], [
					0,
					2.65,
					.3
				], C.black),
				box([
					.08,
					1.2,
					.4
				], [
					0,
					2.2,
					-4.3
				], C.dark),
				box([
					.08,
					.08,
					2.6
				], [
					-.7,
					.4,
					.3
				], C.metal),
				box([
					.08,
					.08,
					2.6
				], [
					.7,
					.4,
					.3
				], C.metal)
			]
		},
		horse_cart: {
			zh: "马车",
			category: "交通",
			doc: "带篷的马车（不含马），车辕朝 +Z",
			build: () => [
				box([
					1.6,
					.25,
					2.4
				], [
					0,
					.9,
					0
				], C.wood),
				box([
					1.6,
					1.3,
					2.2
				], [
					0,
					1.7,
					-.05
				], C.roofDark),
				wheel(1.3, .12, [
					-.9,
					.65,
					0
				]),
				wheel(1.3, .12, [
					.9,
					.65,
					0
				]),
				box([
					.08,
					.08,
					2.4
				], [
					-.35,
					.85,
					2.1
				], C.woodDark),
				box([
					.08,
					.08,
					2.4
				], [
					.35,
					.85,
					2.1
				], C.woodDark)
			]
		},
		tree: {
			zh: "树",
			category: "自然",
			doc: "树。kind：round 阔叶、pine 松、palm 椰、willow 柳",
			params: {
				height: {
					default: 5,
					doc: "高"
				},
				kind: {
					default: "round",
					doc: "树种",
					options: [
						"round",
						"pine",
						"palm",
						"willow"
					]
				}
			},
			build: (p) => {
				const H = n(p.height, 5), k = s(p.kind, "round");
				if (k === "pine") return [
					cyl(.3, H * .3, [
						0,
						H * .15,
						0
					], C.trunk, void 0, 6),
					cone(H * .55, H * .45, [
						0,
						H * .45,
						0
					], C.foliageDark, 7),
					cone(H * .42, H * .4, [
						0,
						H * .68,
						0
					], C.foliageDark, 7),
					cone(H * .28, H * .3, [
						0,
						H * .88,
						0
					], C.foliageDark, 7)
				];
				if (k === "palm") {
					const parts = [cyl(.28, H, [
						0,
						H / 2,
						0
					], C.trunk, [
						3,
						0,
						0
					], 6)];
					for (let i = 0; i < 6; i++) parts.push(box([
						.5,
						.06,
						H * .45
					], [
						Math.sin(i) * H * .18,
						H - .1,
						Math.cos(i) * H * .18
					], C.foliage, [
						-25,
						i * 360 / 6,
						0
					]));
					return parts;
				}
				if (k === "willow") return [
					cyl(.4, H * .5, [
						0,
						H * .25,
						0
					], C.trunk, void 0, 6),
					ball([
						H * .7,
						H * .45,
						H * .7
					], [
						0,
						H * .7,
						0
					], C.foliage),
					cone(H * .75, H * .55, [
						0,
						H * .35,
						0
					], C.foliage, 9, [
						180,
						0,
						0
					])
				];
				return [cyl(.32, H * .45, [
					0,
					H * .225,
					0
				], C.trunk, void 0, 6), ball([
					H * .55,
					H * .5,
					H * .55
				], [
					0,
					H * .68,
					0
				], C.foliage, 7)];
			}
		},
		bush: {
			zh: "灌木",
			category: "自然",
			doc: "一丛灌木",
			params: { size: {
				default: 1.2,
				doc: "大小"
			} },
			build: (p) => {
				const k = n(p.size, 1.2);
				return [ball([
					k * 1.3,
					k * .8,
					k * 1.1
				], [
					0,
					k * .4,
					0
				], C.foliageDark, 6), ball([
					k * .8,
					k * .7,
					k * .8
				], [
					k * .4,
					k * .45,
					k * .2
				], C.foliage, 6)];
			}
		},
		rock: {
			zh: "石头",
			category: "自然",
			doc: "一块石头",
			params: { size: {
				default: 1,
				doc: "大小"
			} },
			build: (p) => {
				const k = n(p.size, 1);
				return [ball([
					k * 1.2,
					k * .75,
					k
				], [
					0,
					k * .3,
					0
				], C.roofDark, 5)];
			}
		},
		mountain: {
			zh: "远山",
			category: "自然",
			doc: "远景的山（很大，放远处当背景）",
			params: {
				height: {
					default: 30,
					doc: "高"
				},
				width: {
					default: 70,
					doc: "底宽"
				}
			},
			build: (p) => [cone(n(p.width, 70), n(p.height, 30), [
				0,
				n(p.height, 30) / 2,
				0
			], "#c7ced7", 7)]
		},
		flower_bed: {
			zh: "花坛",
			category: "自然",
			doc: "方形花坛",
			params: { width: {
				default: 2,
				doc: "宽"
			} },
			build: (p) => {
				const w = n(p.width, 2);
				return [box([
					w,
					.4,
					w
				], [
					0,
					.2,
					0
				], C.wall2), ball([
					w * .9,
					.5,
					w * .9
				], [
					0,
					.5,
					0
				], "#c98fa0", 6)];
			}
		},
		table: {
			zh: "桌子",
			category: "室内",
			doc: "桌子。shape：square 方桌、round 圆桌",
			params: {
				shape: {
					default: "square",
					doc: "形状",
					options: ["square", "round"]
				},
				width: {
					default: 1.2,
					doc: "宽/直径"
				}
			},
			build: (p) => {
				const w = n(p.width, 1.2);
				if (s(p.shape, "square") === "round") return [
					cyl(w, .06, [
						0,
						.76,
						0
					], C.wood, void 0, 16),
					cyl(.12, .73, [
						0,
						.37,
						0
					], C.woodDark, void 0, 8),
					cyl(.6, .04, [
						0,
						.02,
						0
					], C.woodDark, void 0, 12)
				];
				return [box([
					w,
					.06,
					w * .8
				], [
					0,
					.76,
					0
				], C.wood), ...[
					[-1, -1],
					[1, -1],
					[-1, 1],
					[1, 1]
				].map(([x, z]) => box([
					.06,
					.73,
					.06
				], [
					x * (w / 2 - .08),
					.37,
					z * (w * .4 - .08)
				], C.woodDark))];
			}
		},
		chair: {
			zh: "椅子",
			category: "室内",
			doc: "椅子，坐的人面朝 +Z",
			build: () => [
				box([
					.48,
					.06,
					.46
				], [
					0,
					.46,
					0
				], C.wood),
				box([
					.48,
					.55,
					.05
				], [
					0,
					.76,
					-.21
				], C.wood),
				...[
					[-1, -1],
					[1, -1],
					[-1, 1],
					[1, 1]
				].map(([x, z]) => box([
					.05,
					.44,
					.05
				], [
					x * .2,
					.22,
					z * .19
				], C.woodDark))
			]
		},
		stool: {
			zh: "凳子",
			category: "室内",
			doc: "圆凳",
			build: () => [cyl(.36, .05, [
				0,
				.45,
				0
			], C.wood, void 0, 10), cyl(.3, .42, [
				0,
				.21,
				0
			], C.woodDark, void 0, 8)]
		},
		sofa: {
			zh: "沙发",
			category: "室内",
			doc: "三人沙发，坐的人面朝 +Z",
			params: { color: {
				default: "#9aa6b8",
				doc: "颜色"
			} },
			build: (p) => {
				const c = s(p.color, "#9aa6b8");
				return [
					box([
						2.1,
						.45,
						.9
					], [
						0,
						.22,
						0
					], c),
					box([
						2.1,
						.5,
						.2
					], [
						0,
						.7,
						-.35
					], c),
					box([
						.2,
						.3,
						.9
					], [
						-.95,
						.55,
						0
					], c),
					box([
						.2,
						.3,
						.9
					], [
						.95,
						.55,
						0
					], c)
				];
			}
		},
		bed: {
			zh: "床",
			category: "室内",
			doc: "双人床，床头在 -Z",
			build: () => [
				box([
					1.6,
					.35,
					2.1
				], [
					0,
					.18,
					0
				], C.woodDark),
				box([
					1.5,
					.2,
					2
				], [
					0,
					.45,
					.02
				], C.white),
				box([
					1.6,
					.9,
					.08
				], [
					0,
					.6,
					-1.04
				], C.woodDark),
				box([
					1.2,
					.12,
					.4
				], [
					0,
					.61,
					-.75
				], C.wall2)
			]
		},
		desk: {
			zh: "书桌",
			category: "室内",
			doc: "书桌／办公桌。人一般坐在它的 -Z 一侧、面朝 +Z",
			build: () => [
				box([
					1.4,
					.05,
					.7
				], [
					0,
					.75,
					0
				], C.wood),
				box([
					.05,
					.73,
					.68
				], [
					-.66,
					.37,
					0
				], C.woodDark),
				box([
					.05,
					.73,
					.68
				], [
					.66,
					.37,
					0
				], C.woodDark)
			]
		},
		shelf: {
			zh: "书架",
			category: "室内",
			doc: "靠墙书架，正面朝 +Z",
			build: () => {
				const parts = [box([
					1.2,
					2,
					.35
				], [
					0,
					1,
					0
				], C.wood)];
				for (let i = 1; i < 5; i++) parts.push(box([
					1.1,
					.26,
					.05
				], [
					0,
					.4 * i,
					.16
				], C.woodDark));
				return parts;
			}
		},
		door: {
			zh: "门",
			category: "室内",
			doc: "门框＋门扇，门扇朝 +Z",
			params: {
				width: {
					default: 1,
					doc: "宽"
				},
				height: {
					default: 2.1,
					doc: "高"
				}
			},
			build: (p) => {
				const w = n(p.width, 1), h = n(p.height, 2.1);
				return [box([
					w + .2,
					h + .1,
					.12
				], [
					0,
					(h + .1) / 2,
					0
				], C.wall2), box([
					w,
					h,
					.06
				], [
					0,
					h / 2,
					.06
				], C.woodDark)];
			}
		},
		window: {
			zh: "窗",
			category: "室内",
			doc: "窗框（挂在墙上用 y 调高度）",
			params: {
				width: {
					default: 1.2,
					doc: "宽"
				},
				height: {
					default: 1.2,
					doc: "高"
				}
			},
			build: (p) => {
				const w = n(p.width, 1.2), h = n(p.height, 1.2);
				return [box([
					w,
					h,
					.08
				], [
					0,
					h / 2,
					0
				], C.wall2), box([
					w * .85,
					h * .85,
					.1
				], [
					0,
					h / 2,
					.01
				], C.glass)];
			}
		},
		counter: {
			zh: "柜台",
			category: "室内",
			doc: "柜台，客人一侧朝 +Z",
			params: { length: {
				default: 2.4,
				doc: "长"
			} },
			build: (p) => {
				const l = n(p.length, 2.4);
				return [box([
					l,
					1.05,
					.6
				], [
					0,
					.52,
					0
				], C.wood), box([
					l + .1,
					.05,
					.7
				], [
					0,
					1.08,
					0
				], C.woodDark)];
			}
		},
		screen: {
			zh: "屏风",
			category: "室内",
			doc: "四扇屏风，沿 X 展开",
			build: () => [
				-1.2,
				-.4,
				.4,
				1.2
			].map((x, i) => box([
				.78,
				1.8,
				.04
			], [
				x,
				.95,
				i % 2 ? .08 : -.08
			], C.wood, [
				0,
				i % 2 ? 12 : -12,
				0
			]))
		},
		cabinet: {
			zh: "柜子",
			category: "室内",
			doc: "立柜，正面朝 +Z",
			build: () => [box([
				1,
				1.9,
				.55
			], [
				0,
				.95,
				0
			], C.wood), box([
				.02,
				1.7,
				.02
			], [
				0,
				.95,
				.28
			], C.woodDark)]
		},
		floor_lamp: {
			zh: "落地灯",
			category: "室内",
			doc: "落地灯",
			build: () => [
				cyl(.3, .04, [
					0,
					.02,
					0
				], C.dark, void 0, 10),
				cyl(.04, 1.5, [
					0,
					.77,
					0
				], C.dark, void 0, 6),
				{
					...cone(.45, .35, [
						0,
						1.6,
						0
					], C.light, 10),
					glow: true
				}
			]
		},
		crate: {
			zh: "木箱",
			category: "道具",
			doc: "木箱",
			params: { size: {
				default: .8,
				doc: "边长"
			} },
			build: (p) => {
				const k = n(p.size, .8);
				return [box([
					k,
					k,
					k
				], [
					0,
					k / 2,
					0
				], C.wood), box([
					k + .02,
					.08,
					k + .02
				], [
					0,
					k * .8,
					0
				], C.woodDark)];
			}
		},
		barrel: {
			zh: "木桶",
			category: "道具",
			doc: "木桶",
			build: () => [
				cyl(.6, .9, [
					0,
					.45,
					0
				], C.wood, void 0, 12),
				cyl(.63, .06, [
					0,
					.2,
					0
				], C.dark, void 0, 12),
				cyl(.63, .06, [
					0,
					.7,
					0
				], C.dark, void 0, 12)
			]
		},
		sack: {
			zh: "麻袋",
			category: "道具",
			doc: "装满的麻袋",
			build: () => [ball([
				.6,
				.7,
				.45
			], [
				0,
				.35,
				0
			], C.wood, 6)]
		},
		cart: {
			zh: "手推车",
			category: "道具",
			doc: "两轮手推车，把手朝 -Z",
			build: () => [
				box([
					1,
					.35,
					1.3
				], [
					0,
					.75,
					0
				], C.wood),
				wheel(.9, .08, [
					-.58,
					.45,
					.1
				]),
				wheel(.9, .08, [
					.58,
					.45,
					.1
				]),
				box([
					.06,
					.06,
					1.1
				], [
					-.35,
					.75,
					-1.1
				], C.woodDark),
				box([
					.06,
					.06,
					1.1
				], [
					.35,
					.75,
					-1.1
				], C.woodDark)
			]
		},
		lantern: {
			zh: "灯笼",
			category: "道具",
			doc: "红灯笼（用 at 的 y 挂到高处，比如 [x, 3, z]）",
			build: () => [
				{
					...ball([
						.45,
						.55,
						.45
					], [
						0,
						.35,
						0
					], C.red, 10),
					glow: true
				},
				cyl(.2, .06, [
					0,
					.64,
					0
				], C.yellow, void 0, 8),
				cyl(.2, .06, [
					0,
					.06,
					0
				], C.yellow, void 0, 8)
			]
		},
		flag: {
			zh: "旗帜",
			category: "道具",
			doc: "旗杆＋旗面（旗面朝 +X 展开）",
			params: {
				color: {
					default: "#d65a55",
					doc: "旗色"
				},
				height: {
					default: 4,
					doc: "杆高"
				}
			},
			build: (p) => {
				const h = n(p.height, 4);
				return [cyl(.08, h, [
					0,
					h / 2,
					0
				], C.metal, void 0, 6), box([
					1.3,
					.8,
					.03
				], [
					.68,
					h - .45,
					0
				], s(p.color, C.red))];
			}
		},
		weapon_rack: {
			zh: "兵器架",
			category: "道具",
			doc: "兵器架（几根长杆斜靠）",
			build: () => [
				box([
					1.6,
					.1,
					.4
				], [
					0,
					.05,
					0
				], C.woodDark),
				box([
					1.6,
					.1,
					.1
				], [
					0,
					1.2,
					-.15
				], C.woodDark),
				...[
					-.6,
					-.2,
					.2,
					.6
				].map((x) => box([
					.05,
					2.2,
					.05
				], [
					x,
					1.1,
					0
				], C.dark, [
					8,
					0,
					0
				]))
			]
		},
		marker: {
			zh: "区域标记",
			category: "标记",
			doc: "地面上的半透明色块（标出区域，不出现在成片里）",
			params: {
				width: {
					default: 4,
					doc: "宽"
				},
				depth: {
					default: 4,
					doc: "深"
				},
				color: {
					default: "#4aa3ff",
					doc: "颜色"
				}
			},
			build: (p) => [{
				...box([
					n(p.width, 4),
					.02,
					n(p.depth, 4)
				], [
					0,
					.02,
					0
				], s(p.color, "#4aa3ff")),
				opacity: .35
			}]
		},
		arrow: {
			zh: "方向箭头",
			category: "标记",
			doc: "地面箭头，指向 +Z",
			params: {
				length: {
					default: 3,
					doc: "长"
				},
				color: {
					default: "#ffb400",
					doc: "颜色"
				}
			},
			build: (p) => {
				const l = n(p.length, 3), c = s(p.color, "#ffb400");
				return [box([
					.3,
					.03,
					l * .7
				], [
					0,
					.03,
					-l * .15
				], c), prism([
					1,
					l * .3,
					.06
				], [
					0,
					.03,
					l * .35
				], c, [
					90,
					0,
					0
				])];
			}
		},
		image_board: {
			zh: "图片板",
			category: "标记",
			doc: "竖立的图片板（url 贴图，正面朝 +Z），可当背景或参考",
			params: {
				width: {
					default: 4,
					doc: "宽"
				},
				height: {
					default: 3,
					doc: "高"
				},
				url: {
					default: "",
					doc: "图片地址"
				}
			},
			build: (p) => {
				const w = n(p.width, 4), h = n(p.height, 3);
				return [box([
					w,
					h,
					.06
				], [
					0,
					h / 2,
					0
				], C.white)];
			}
		},
		bird: {
			zh: "鸟",
			category: "动物",
			doc: "飞鸟（展翅），头朝 +Z；用 at 的 y 放到空中",
			build: () => [
				ball([
					.3,
					.3,
					.7
				], [
					0,
					0,
					0
				], C.dark, 6),
				box([
					1.2,
					.03,
					.35
				], [
					0,
					.05,
					0
				], C.dark, [
					0,
					0,
					8
				]),
				cone(.1, .2, [
					0,
					0,
					.43
				], C.yellow, 5, [
					90,
					0,
					0
				])
			]
		},
		horse: {
			zh: "马",
			category: "动物",
			doc: "马，头朝 +Z",
			build: () => [
				box([
					.6,
					.7,
					1.7
				], [
					0,
					1.35,
					0
				], C.woodDark),
				box([
					.35,
					.8,
					.4
				], [
					0,
					1.85,
					.85
				], C.woodDark, [
					30,
					0,
					0
				]),
				box([
					.3,
					.35,
					.65
				], [
					0,
					2.2,
					1.2
				], C.woodDark),
				...[
					[-1, -1],
					[1, -1],
					[-1, 1],
					[1, 1]
				].map(([x, z]) => box([
					.14,
					1,
					.14
				], [
					x * .2,
					.5,
					z * .65
				], C.woodDark)),
				box([
					.08,
					.6,
					.08
				], [
					0,
					1.2,
					-.95
				], C.dark, [
					-30,
					0,
					0
				])
			]
		},
		dog: {
			zh: "狗",
			category: "动物",
			doc: "狗，头朝 +Z",
			build: () => [
				box([
					.3,
					.3,
					.7
				], [
					0,
					.45,
					0
				], C.wood),
				box([
					.25,
					.25,
					.3
				], [
					0,
					.65,
					.42
				], C.wood),
				...[
					[-1, -1],
					[1, -1],
					[-1, 1],
					[1, 1]
				].map(([x, z]) => box([
					.08,
					.32,
					.08
				], [
					x * .1,
					.16,
					z * .25
				], C.wood))
			]
		}
	};
	function carParts(color) {
		return [
			box([
				1.8,
				.7,
				4.5
			], [
				0,
				.6,
				0
			], color),
			box([
				1.6,
				.62,
				2.3
			], [
				0,
				1.25,
				-.25
			], "#cfd8e2"),
			box([
				1.62,
				.1,
				2.32
			], [
				0,
				1.58,
				-.25
			], color),
			wheel(.66, .26, [
				-.86,
				.33,
				1.45
			]),
			wheel(.66, .26, [
				.86,
				.33,
				1.45
			]),
			wheel(.66, .26, [
				-.86,
				.33,
				-1.45
			]),
			wheel(.66, .26, [
				.86,
				.33,
				-1.45
			]),
			{
				...box([
					.42,
					.14,
					.05
				], [
					-.6,
					.7,
					2.26
				], C.light),
				glow: true
			},
			{
				...box([
					.42,
					.14,
					.05
				], [
					.6,
					.7,
					2.26
				], C.light),
				glow: true
			},
			box([
				.42,
				.14,
				.05
			], [
				-.6,
				.7,
				-2.26
			], C.red),
			box([
				.42,
				.14,
				.05
			], [
				.6,
				.7,
				-2.26
			], C.red)
		];
	}
	/** 部件表的包围盒（局部，粗略：只考虑绕 Y 转 90° 的换轴）。 */
	function partsBounds(parts) {
		const min = [
			Infinity,
			Infinity,
			Infinity
		];
		const max = [
			-Infinity,
			-Infinity,
			-Infinity
		];
		for (const p of parts) {
			let [sx, sy, sz] = p.size;
			if (p.prim === "torus") {
				sx = p.size[0];
				sy = p.size[0];
				sz = p.size[1];
			}
			const ry = Math.abs(((p.rot?.[1] ?? 0) % 180 + 180) % 180);
			if (ry > 45 && ry < 135) [sx, sz] = [sz, sx];
			const rx = Math.abs(((p.rot?.[0] ?? 0) % 180 + 180) % 180);
			if (rx > 45 && rx < 135) [sy, sz] = [sz, sy];
			const half = [
				sx / 2,
				sy / 2,
				sz / 2
			];
			for (let i = 0; i < 3; i++) {
				min[i] = Math.min(min[i], p.pos[i] - half[i]);
				max[i] = Math.max(max[i], p.pos[i] + half[i]);
			}
		}
		if (!Number.isFinite(min[0])) return {
			min: [
				0,
				0,
				0
			],
			max: [
				0,
				0,
				0
			]
		};
		return {
			min,
			max
		};
	}
	function prefabDefaults(name) {
		const def = PREFABS[name];
		const out = {};
		for (const [k, v] of Object.entries(def?.params ?? {})) out[k] = v.default;
		return out;
	}
	/** 体型：身高（米）与比例。渲染用同一张表。 */
	const BODIES = {
		male: {
			zh: "标准男性",
			height: 1.75,
			width: 1,
			head: 1
		},
		female: {
			zh: "标准女性",
			height: 1.65,
			width: .9,
			head: 1
		},
		teen: {
			zh: "少年",
			height: 1.6,
			width: .88,
			head: 1.04
		},
		child: {
			zh: "儿童",
			height: 1.25,
			width: .8,
			head: 1.18
		},
		chibi: {
			zh: "二头身",
			height: 1.05,
			width: .95,
			head: 1.9
		},
		slim: {
			zh: "纤细",
			height: 1.72,
			width: .8,
			head: 1
		},
		muscular: {
			zh: "健硕",
			height: 1.82,
			width: 1.22,
			head: 1
		},
		broad: {
			zh: "宽厚",
			height: 1.76,
			width: 1.3,
			head: 1.02
		},
		elder: {
			zh: "老人",
			height: 1.62,
			width: .95,
			head: 1
		}
	};
	const POSES = {
		stand: "站立",
		walk: "行走",
		run: "奔跑",
		sit: "坐",
		crouch: "蹲",
		kneel: "跪",
		point: "指向前方",
		wave: "挥手",
		fight: "格斗架势",
		lie: "躺",
		phone: "打电话",
		arms_crossed: "抱臂",
		hands_up: "举手投降",
		drive: "开车（坐姿，双手前伸）",
		aim: "举枪瞄准",
		bow: "鞠躬"
	};
	/** 给 LLM 和界面用的目录：预制件、体型、姿势。 */
	function catalogDoc() {
		return {
			prefabs: Object.entries(PREFABS).map(([name, d]) => {
				const bb = partsBounds(d.build(prefabDefaults(name)));
				return {
					name,
					zh: d.zh,
					category: d.category,
					doc: d.doc,
					size: [
						0,
						1,
						2
					].map((i) => +(bb.max[i] - bb.min[i]).toFixed(2)),
					params: Object.fromEntries(Object.entries(d.params ?? {}).map(([k, v]) => [k, {
						default: v.default,
						doc: v.doc,
						...v.options ? { options: v.options } : {}
					}]))
				};
			}),
			bodies: Object.entries(BODIES).map(([name, v]) => ({
				name,
				zh: v.zh,
				height: v.height
			})),
			poses: Object.entries(POSES).map(([name, zh]) => ({
				name,
				zh
			}))
		};
	}
	//#endregion
	//#region src/scene/math.ts
	const add = (a, b) => [
		a[0] + b[0],
		a[1] + b[1],
		a[2] + b[2]
	];
	const sub = (a, b) => [
		a[0] - b[0],
		a[1] - b[1],
		a[2] - b[2]
	];
	const scale = (a, k) => [
		a[0] * k,
		a[1] * k,
		a[2] * k
	];
	const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
	const len = (a) => Math.hypot(a[0], a[1], a[2]);
	const dist = (a, b) => len(sub(a, b));
	const norm = (a) => {
		const l = len(a) || 1;
		return scale(a, 1 / l);
	};
	const lerp = (a, b, t) => a + (b - a) * t;
	const lerp3 = (a, b, t) => [
		lerp(a[0], b[0], t),
		lerp(a[1], b[1], t),
		lerp(a[2], b[2], t)
	];
	const rad = (d) => d * Math.PI / 180;
	const deg = (r) => r * 180 / Math.PI;
	const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
	/** 物体朝向（yaw，度）→ 前方单位向量。yaw 0 = +Z，yaw 90 = +X。 */
	const forwardOf = (yaw) => [
		Math.sin(rad(yaw)),
		0,
		Math.cos(rad(yaw))
	];
	/** 物体自己的右手方向（面向 +Z 时右手在 -X）。 */
	const rightOf = (yaw) => [
		-Math.cos(rad(yaw)),
		0,
		Math.sin(rad(yaw))
	];
	/** 从 a 看向 b 的 yaw（度）。 */
	const yawTo = (a, b) => deg(Math.atan2(b[0] - a[0], b[2] - a[2]));
	/** 目标局部偏移（x 右、y 上、z 前）→ 世界偏移。 */
	function localToWorld(offset, yaw) {
		const f = forwardOf(yaw);
		const r = rightOf(yaw);
		return [
			r[0] * offset[0] + f[0] * offset[2],
			offset[1],
			r[2] * offset[0] + f[2] * offset[2]
		];
	}
	function easeInOut(t) {
		t = clamp(t, 0, 1);
		return t < .5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2;
	}
	/** 可复现的随机数（mulberry32）：同一个 seed，脚本每次跑出同一个场景。 */
	function rng(seed) {
		let a = seed >>> 0 || 1;
		return () => {
			a |= 0;
			a = a + 1831565813 | 0;
			let t = Math.imul(a ^ a >>> 15, 1 | a);
			t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
			return ((t ^ t >>> 14) >>> 0) / 4294967296;
		};
	}
	/** 均匀 Catmull-Rom：p1→p2 之间的 u（0–1）。 */
	function catmull(p0, p1, p2, p3, u) {
		const u2 = u * u;
		const u3 = u2 * u;
		const f = (a, b, c, d) => .5 * (2 * b + (-a + c) * u + (2 * a - 5 * b + 4 * c - d) * u2 + (-a + 3 * b - 3 * c + d) * u3);
		return [
			f(p0[0], p1[0], p2[0], p3[0]),
			f(p0[1], p1[1], p2[1], p3[1]),
			f(p0[2], p1[2], p2[2], p3[2])
		];
	}
	/** 折线总长与按弧长取点。 */
	function polyLength(pts) {
		let s = 0;
		for (let i = 1; i < pts.length; i++) s += dist(pts[i - 1], pts[i]);
		return s;
	}
	function samplePoly(pts, s) {
		if (pts.length === 1) return {
			p: pts[0],
			dir: [
				0,
				0,
				1
			]
		};
		let acc = 0;
		for (let i = 1; i < pts.length; i++) {
			const seg = dist(pts[i - 1], pts[i]);
			if (acc + seg >= s || i === pts.length - 1) {
				const u = seg > 0 ? clamp((s - acc) / seg, 0, 1) : 0;
				return {
					p: lerp3(pts[i - 1], pts[i], u),
					dir: norm(sub(pts[i], pts[i - 1]))
				};
			}
			acc += seg;
		}
		return {
			p: pts[pts.length - 1],
			dir: [
				0,
				0,
				1
			]
		};
	}
	/** 把一串控制点加密成平滑曲线（Catmull-Rom，每段 n 个点）。 */
	function smoothPath(pts, n = 8) {
		if (pts.length < 3) return pts.slice();
		const out = [];
		for (let i = 0; i < pts.length - 1; i++) {
			const p0 = pts[Math.max(0, i - 1)];
			const p3 = pts[Math.min(pts.length - 1, i + 2)];
			for (let k = 0; k < n; k++) out.push(catmull(p0, pts[i], pts[i + 1], p3, k / n));
		}
		out.push(pts[pts.length - 1]);
		return out;
	}
	const v2to3 = (p) => p.length === 2 ? [
		p[0],
		0,
		p[1]
	] : [
		p[0],
		p[1],
		p[2]
	];
	//#endregion
	//#region src/scene/cameraPresets.ts
	/** 景别 → 35mm 下离目标的水平距离（以 1.75m 的人为 1）。 */
	const SHOT_DIST = {
		els: 30,
		ws: 11,
		fs: 5.2,
		mls: 3.6,
		ms: 2.8,
		mcu: 1.9,
		cu: 1.3,
		ecu: .7
	};
	function shotDistance(size, c, k = 1) {
		return (SHOT_DIST[size] ?? 2.8) * Math.max(1, c.size / 1.75) * (c.lens / 35) * k;
	}
	const at = (c, u) => c.start + c.duration * u;
	/** 绕目标的关键帧（有目标）或绕点的世界坐标关键帧（没目标）。 */
	function orb(c, u, angle, radius, height, extra = {}) {
		const t = at(c, u);
		if (c.target) return {
			t,
			orbit: c.target,
			angle,
			radius,
			height,
			...extra
		};
		const p = c.posAt(t);
		const a = angle * Math.PI / 180;
		return {
			t,
			at: [
				p[0] + Math.sin(a) * radius,
				p[1] + height,
				p[2] + Math.cos(a) * radius
			],
			look: [
				p[0],
				p[1] + c.aim,
				p[2]
			],
			...extra
		};
	}
	/** 跟随目标的关键帧：offset 在目标局部系（x 右手、y 上、z 前方）。 */
	function fol(c, u, offset, extra = {}) {
		const t = at(c, u);
		if (c.target) return {
			t,
			follow: c.target,
			offset,
			...extra
		};
		const p = c.posAt(t);
		return {
			t,
			at: add(p, [
				-offset[0],
				offset[1],
				offset[2]
			]),
			look: [
				p[0],
				p[1] + c.aim,
				p[2]
			],
			...extra
		};
	}
	/** 世界坐标关键帧，看向 look（默认看目标瞄准点）。 */
	function world(c, u, pos, look, extra = {}) {
		const t = at(c, u);
		const p = c.posAt(t);
		return {
			t,
			at: pos,
			look: look ?? c.target ?? [
				p[0],
				p[1] + c.aim,
				p[2]
			],
			...extra
		};
	}
	/** 起幅机位：目标正前方偏 angle 度、给定距离与高度处的世界坐标。 */
	function framing(c, dist, height, angle = c.angle) {
		const p = c.posAt(c.start);
		const yaw = c.yawAt(c.start) + angle;
		const fwd = forwardOf(yaw);
		return {
			pos: [
				p[0] + fwd[0] * dist,
				p[1] + height,
				p[2] + fwd[2] * dist
			],
			look: [
				p[0],
				p[1] + c.aim,
				p[2]
			],
			right: rightOf(yaw + 180),
			fwd
		};
	}
	const D = (c, size, k = 1) => c.distance ?? shotDistance(size, c, k);
	const H = (c, dflt) => c.height ?? dflt;
	const CAMERA_PRESETS = [
		{
			id: "static",
			zh: "固定镜头",
			group: "固定",
			doc: "机位不动，中景对着目标",
			build: (c) => ({ keys: [orb(c, 0, c.angle, D(c, "ms"), H(c, c.aim)), orb(c, 1, c.angle, D(c, "ms"), H(c, c.aim))] })
		},
		{
			id: "handheld",
			zh: "手持拍摄",
			group: "固定",
			doc: "手持晃动，略微前移",
			build: (c) => ({
				keys: [orb(c, 0, c.angle, D(c, "ms"), H(c, c.aim)), orb(c, 1, c.angle + 4, D(c, "ms", .9), H(c, c.aim))],
				shake: .6,
				ease: "linear"
			})
		},
		{
			id: "dutch",
			zh: "荷兰角",
			group: "固定",
			doc: "画面倾斜 15° 的固定机位，制造不安",
			build: (c) => ({ keys: [orb(c, 0, c.angle, D(c, "ms"), H(c, c.aim), { roll: 15 }), orb(c, 1, c.angle, D(c, "ms"), H(c, c.aim), { roll: 15 })] })
		},
		{
			id: "push_in",
			zh: "推近",
			group: "推拉",
			doc: "镜头前推：从全景推到中景",
			build: (c) => ({ keys: [orb(c, 0, c.angle, D(c, "fs"), H(c, c.aim)), orb(c, 1, c.angle, D(c, "ms", .85), H(c, c.aim))] })
		},
		{
			id: "pull_out",
			zh: "拉远",
			group: "推拉",
			doc: "镜头后移：从中景拉到远景",
			build: (c) => ({ keys: [orb(c, 0, c.angle, D(c, "ms"), H(c, c.aim)), orb(c, 1, c.angle, D(c, "ws"), H(c, c.aim + 1))] })
		},
		{
			id: "dolly_to_medium",
			zh: "推轨至中景",
			group: "推拉",
			doc: "轨道推进，从远景推到中景",
			build: (c) => ({ keys: [orb(c, 0, c.angle, D(c, "ws"), H(c, c.aim)), orb(c, 1, c.angle, D(c, "ms"), H(c, c.aim))] })
		},
		{
			id: "dolly_in",
			zh: "推轨",
			group: "推拉",
			doc: "轨道平稳推进一段",
			build: (c) => ({
				keys: [orb(c, 0, c.angle, D(c, "fs"), H(c, c.aim)), orb(c, 1, c.angle, D(c, "fs", .6), H(c, c.aim))],
				ease: "linear"
			})
		},
		{
			id: "wide_push_in",
			zh: "远景推近",
			group: "推拉",
			doc: "从高处远景推到全景",
			build: (c) => ({ keys: [orb(c, 0, c.angle, D(c, "ws", 1.4), H(c, 4)), orb(c, 1, c.angle, D(c, "fs"), H(c, c.aim))] })
		},
		{
			id: "extreme_wide_to_close",
			zh: "大远景到特写",
			group: "推拉",
			doc: "从大远景一路推到脸部特写",
			build: (c) => ({
				keys: [
					orb(c, 0, c.angle, D(c, "els"), H(c, 14)),
					orb(c, .7, c.angle, D(c, "ms"), c.aim + .4),
					orb(c, 1, c.angle, D(c, "cu"), c.aim)
				],
				path: "curve"
			})
		},
		{
			id: "medium_to_wide",
			zh: "中景到远景",
			group: "推拉",
			doc: "从中景拉开到远景，交代环境",
			build: (c) => ({ keys: [orb(c, 0, c.angle, D(c, "ms"), H(c, c.aim)), orb(c, 1, c.angle, D(c, "ws", 1.3), H(c, 4))] })
		},
		{
			id: "zoom_in",
			zh: "变焦推进",
			group: "推拉",
			doc: "机位不动，焦段 35→85",
			build: (c) => ({ keys: [orb(c, 0, c.angle, D(c, "fs"), H(c, c.aim), { lens: 35 }), orb(c, 1, c.angle, D(c, "fs"), H(c, c.aim), { lens: 85 })] })
		},
		{
			id: "zoom_out",
			zh: "变焦拉远",
			group: "推拉",
			doc: "机位不动，焦段 85→30",
			build: (c) => ({ keys: [orb(c, 0, c.angle, D(c, "fs"), H(c, c.aim), { lens: 85 }), orb(c, 1, c.angle, D(c, "fs"), H(c, c.aim), { lens: 30 })] })
		},
		{
			id: "dolly_zoom",
			zh: "柯克变焦",
			group: "推拉",
			doc: "推轨变焦（希区柯克）：边推边拉焦，主体大小不变、背景被拉远",
			build: (c) => {
				const d0 = D(c, "ms", 1.8), d1 = D(c, "ms", .8);
				return {
					keys: [orb(c, 0, c.angle, d0, H(c, c.aim), { lens: 60 }), orb(c, 1, c.angle, d1, H(c, c.aim), { lens: 60 * (d1 / d0) })],
					ease: "linear"
				};
			}
		},
		...["pan_left", "pan_right"].map((id) => ({
			id,
			zh: id === "pan_left" ? "镜头左摇" : "镜头右摇",
			group: "摇",
			doc: "机位不动，镜头水平转 35°",
			build: (c) => {
				const f = framing(c, D(c, "fs"), H(c, c.aim));
				const dir = id === "pan_left" ? -1 : 1;
				return { keys: [world(c, 0, f.pos, f.look), world(c, 1, f.pos, add(f.look, scale(f.right, dir * D(c, "fs") * .7)))] };
			}
		})),
		...["tilt_up", "tilt_down"].map((id) => ({
			id,
			zh: id === "tilt_up" ? "镜头上摇" : "镜头下摇",
			group: "摇",
			doc: "机位不动，镜头上抬／下压",
			build: (c) => {
				const f = framing(c, D(c, "fs"), H(c, 1.2));
				const low = add(f.look, [
					0,
					-c.aim + .1,
					0
				]), high = add(f.look, [
					0,
					c.size * 1.5 + 2,
					0
				]);
				return { keys: id === "tilt_up" ? [world(c, 0, f.pos, low), world(c, 1, f.pos, high)] : [world(c, 0, f.pos, high), world(c, 1, f.pos, low)] };
			}
		})),
		{
			id: "whip_pan",
			zh: "甩镜",
			group: "摇",
			doc: "极快横摇 80°（转场用，时长会压到 0.8 秒内）",
			build: (c) => {
				const f = framing(c, D(c, "fs"), H(c, c.aim));
				const d = Math.min(c.duration, .8);
				return {
					keys: [world(c, 0, f.pos, f.look), {
						...world(c, 0, f.pos, add(f.look, scale(f.right, D(c, "fs") * 1.2))),
						t: c.start + d
					}],
					ease: "smooth"
				};
			}
		},
		...["truck_left", "truck_right"].map((id) => ({
			id,
			zh: id === "truck_left" ? "镜头左移" : "横移",
			group: "移",
			doc: "机位沿轨道横向平移 3m，朝向不变",
			build: (c) => {
				const f = framing(c, D(c, "fs"), H(c, c.aim));
				const m = scale(f.right, (id === "truck_left" ? -1 : 1) * 3);
				return {
					keys: [world(c, 0, f.pos, f.look), world(c, 1, add(f.pos, m), add(f.look, m))],
					ease: "linear"
				};
			}
		})),
		...["pedestal_up", "pedestal_down"].map((id) => ({
			id,
			zh: id === "pedestal_up" ? "镜头上升" : "镜头下降",
			group: "移",
			doc: "机位垂直升／降 2.5m，朝向不变",
			build: (c) => {
				const f = framing(c, D(c, "fs"), H(c, id === "pedestal_up" ? 1 : 3.5));
				const m = [
					0,
					id === "pedestal_up" ? 2.5 : -2.5,
					0
				];
				return { keys: [world(c, 0, f.pos, f.look), world(c, 1, add(f.pos, m), add(f.look, m))] };
			}
		})),
		{
			id: "crane_up",
			zh: "摇臂上升",
			group: "移",
			doc: "摇臂从低处升到高处，始终对着目标",
			build: (c) => ({ keys: [orb(c, 0, c.angle, D(c, "fs"), .8), orb(c, 1, c.angle, D(c, "fs", 1.3), H(c, 6))] })
		},
		{
			id: "jib",
			zh: "摇臂",
			group: "移",
			doc: "抛物线：摇臂升起越过再落到新构图",
			build: (c) => ({
				keys: [
					orb(c, 0, c.angle - 20, D(c, "fs"), 1),
					orb(c, .5, c.angle, D(c, "fs"), H(c, 5)),
					orb(c, 1, c.angle + 25, D(c, "ms"), c.aim)
				],
				path: "curve"
			})
		},
		{
			id: "follow",
			zh: "跟随拍摄",
			group: "跟拍",
			doc: "跟在目标身后中景跟拍",
			build: (c) => ({
				keys: [fol(c, 0, [
					0,
					H(c, c.aim + .2),
					-D(c, "ms", 1.3)
				]), fol(c, 1, [
					0,
					H(c, c.aim + .2),
					-D(c, "ms", 1.3)
				])],
				ease: "linear"
			})
		},
		{
			id: "follow_back",
			zh: "背跟",
			group: "跟拍",
			doc: "身后跟拍",
			build: (c) => ({
				keys: [fol(c, 0, [
					0,
					H(c, c.aim + .3),
					-D(c, "fs", .8)
				]), fol(c, 1, [
					0,
					H(c, c.aim + .3),
					-D(c, "fs", .8)
				])],
				ease: "linear"
			})
		},
		{
			id: "follow_back_close",
			zh: "背跟特写",
			group: "跟拍",
			doc: "贴着肩后跟拍",
			build: (c) => ({
				keys: [fol(c, 0, [
					.35 * c.side,
					H(c, c.aim),
					-D(c, "cu")
				]), fol(c, 1, [
					.35 * c.side,
					H(c, c.aim),
					-D(c, "cu")
				])],
				ease: "linear"
			})
		},
		{
			id: "follow_front",
			zh: "正面跟",
			group: "跟拍",
			doc: "在目标前方倒退着跟拍",
			build: (c) => ({
				keys: [fol(c, 0, [
					0,
					H(c, c.aim),
					D(c, "ms", 1.3)
				]), fol(c, 1, [
					0,
					H(c, c.aim),
					D(c, "ms", 1.3)
				])],
				ease: "linear"
			})
		},
		{
			id: "follow_front_wide",
			zh: "正面跟远景",
			group: "跟拍",
			doc: "前方远处高位跟拍",
			build: (c) => ({
				keys: [fol(c, 0, [
					0,
					H(c, 3),
					D(c, "ws")
				]), fol(c, 1, [
					0,
					H(c, 3),
					D(c, "ws")
				])],
				ease: "linear"
			})
		},
		{
			id: "follow_side_push",
			zh: "侧跟推近",
			group: "跟拍",
			doc: "侧面跟拍并逐渐推近",
			build: (c) => ({ keys: [fol(c, 0, [
				D(c, "fs") * c.side,
				H(c, c.aim),
				.4
			]), fol(c, 1, [
				D(c, "ms", .8) * c.side,
				H(c, c.aim),
				.3
			])] })
		},
		{
			id: "follow_wide",
			zh: "远景跟随",
			group: "跟拍",
			doc: "侧后方高位远景跟随",
			build: (c) => ({
				keys: [fol(c, 0, [
					D(c, "ws", .7) * c.side,
					H(c, 5),
					-D(c, "ws", .7)
				]), fol(c, 1, [
					D(c, "ws", .7) * c.side,
					H(c, 5),
					-D(c, "ws", .7)
				])],
				ease: "linear"
			})
		},
		{
			id: "front_to_back",
			zh: "正面转背跟",
			group: "跟拍",
			doc: "从正面绕到背后继续跟",
			build: (c) => ({ keys: [orb(c, 0, 0, D(c, "ms", 1.2), H(c, c.aim)), orb(c, 1, 180 * c.side, D(c, "ms", 1.2), H(c, c.aim))] })
		},
		{
			id: "top_to_follow",
			zh: "顶拍转跟随",
			group: "跟拍",
			doc: "先正上方俯拍，再降到身后跟拍",
			build: (c) => {
				const p = c.posAt(c.start);
				return {
					keys: [
						world(c, 0, [
							p[0],
							p[1] + 16,
							p[2] + .1
						]),
						fol(c, .6, [
							0,
							2.2,
							-D(c, "fs")
						]),
						fol(c, 1, [
							0,
							H(c, c.aim + .3),
							-D(c, "fs", .8)
						])
					],
					path: "curve"
				};
			}
		},
		{
			id: "first_person",
			zh: "第一视角",
			group: "跟拍",
			doc: "从目标眼睛的位置往前看（主观镜头）",
			build: (c) => {
				const eye = c.size * .93;
				const key = (u) => fol(c, u, [
					0,
					eye,
					.2
				], c.target ? { look: {
					target: c.target,
					offset: [
						0,
						eye * .95,
						10
					]
				} } : {});
				return {
					keys: [key(0), key(1)],
					ease: "linear",
					shake: .25
				};
			}
		},
		{
			id: "orbit_left",
			zh: "左环绕",
			group: "环绕",
			doc: "绕目标向左（机位自己的左手）走 120°",
			build: (c) => ({ keys: [orb(c, 0, c.angle, D(c, "fs", .9), H(c, c.aim)), orb(c, 1, c.angle + 120, D(c, "fs", .9), H(c, c.aim))] })
		},
		{
			id: "orbit_right",
			zh: "右环绕",
			group: "环绕",
			doc: "绕目标向右走 120°",
			build: (c) => ({ keys: [orb(c, 0, c.angle, D(c, "fs", .9), H(c, c.aim)), orb(c, 1, c.angle - 120, D(c, "fs", .9), H(c, c.aim))] })
		},
		{
			id: "orbit",
			zh: "环绕",
			group: "环绕",
			doc: "绕目标一整圈",
			build: (c) => ({
				keys: [orb(c, 0, c.angle, D(c, "fs", .9), H(c, c.aim)), orb(c, 1, c.angle + 360 * c.side, D(c, "fs", .9), H(c, c.aim))],
				ease: "linear"
			})
		},
		{
			id: "half_arc",
			zh: "半弧",
			group: "环绕",
			doc: "绕目标半圈（180°）",
			build: (c) => ({ keys: [orb(c, 0, c.angle, D(c, "fs", .9), H(c, c.aim)), orb(c, 1, c.angle + 180 * c.side, D(c, "fs", .9), H(c, c.aim))] })
		},
		{
			id: "orbit_twice",
			zh: "环绕两周",
			group: "环绕",
			doc: "绕目标两整圈",
			build: (c) => ({
				keys: [orb(c, 0, c.angle, D(c, "fs", .9), H(c, c.aim)), orb(c, 1, c.angle + 720 * c.side, D(c, "fs", .9), H(c, c.aim))],
				ease: "linear"
			})
		},
		{
			id: "orbit_push",
			zh: "环绕推近",
			group: "环绕",
			doc: "边绕 90° 边推到中近景",
			build: (c) => ({ keys: [orb(c, 0, c.angle, D(c, "fs"), H(c, c.aim)), orb(c, 1, c.angle + 90 * c.side, D(c, "mcu"), c.aim)] })
		},
		{
			id: "spiral_up",
			zh: "螺旋上升",
			group: "环绕",
			doc: "盘旋抬升：绕一圈同时升高拉远",
			build: (c) => ({ keys: [orb(c, 0, c.angle, D(c, "fs"), H(c, c.aim)), orb(c, 1, c.angle + 360 * c.side, D(c, "ws", .8), 9)] })
		},
		{
			id: "spiral_down",
			zh: "盘旋下降",
			group: "环绕",
			doc: "从高处绕一圈降下来推近",
			build: (c) => ({ keys: [orb(c, 0, c.angle, D(c, "ws", .8), 9), orb(c, 1, c.angle + 360 * c.side, D(c, "fs"), H(c, c.aim))] })
		},
		{
			id: "push_turn_left",
			zh: "推近左转",
			group: "环绕",
			doc: "推近的同时向左转 45°",
			build: (c) => ({ keys: [orb(c, 0, c.angle, D(c, "fs"), H(c, c.aim)), orb(c, 1, c.angle + 45, D(c, "ms"), c.aim)] })
		},
		{
			id: "drone",
			zh: "无人机",
			group: "航拍",
			doc: "无人机从后上方高速掠过目标",
			build: (c) => {
				const p0 = c.posAt(c.start), p1 = c.posAt(c.start + c.duration);
				const f = forwardOf(c.yawAt(c.start));
				return {
					keys: [
						world(c, 0, add(p0, [
							-f[0] * 25,
							14,
							-f[2] * 25
						])),
						world(c, .5, add(p0, [
							0,
							9,
							.5
						])),
						world(c, 1, add(p1, [
							f[0] * 20,
							7,
							f[2] * 20
						]))
					],
					path: "curve",
					ease: "linear"
				};
			}
		},
		{
			id: "aerial_high",
			zh: "高空航拍",
			group: "航拍",
			doc: "正上方高空俯拍，缓慢升高",
			build: (c) => {
				const p = c.posAt(c.start);
				return { keys: [world(c, 0, [
					p[0],
					p[1] + 40,
					p[2] + .1
				], void 0, { lens: 28 }), world(c, 1, [
					p[0],
					p[1] + 55,
					p[2] + .1
				], void 0, { lens: 28 })] };
			}
		},
		{
			id: "aerial_rise",
			zh: "航拍拉升",
			group: "航拍",
			doc: "从中景拉升后退到高空全景",
			build: (c) => ({ keys: [orb(c, 0, c.angle, D(c, "ms"), H(c, c.aim)), orb(c, 1, c.angle, D(c, "ws", 1.6), 16)] })
		},
		{
			id: "roll",
			zh: "滚筒旋转",
			group: "特殊",
			doc: "机位不动，画面绕光轴转一整圈",
			build: (c) => ({
				keys: [orb(c, 0, c.angle, D(c, "fs"), H(c, c.aim), { roll: 0 }), orb(c, 1, c.angle, D(c, "fs"), H(c, c.aim), { roll: 360 })],
				ease: "linear"
			})
		}
	];
	const PRESET_IDS = CAMERA_PRESETS.map((p) => p.id);
	function presetDoc() {
		return CAMERA_PRESETS.map((p) => ({
			id: p.id,
			zh: p.zh,
			group: p.group,
			doc: p.doc
		}));
	}
	//#endregion
	//#region src/scene/evaluate.ts
	const EPS = 1e-4;
	function sortedKeys(keys) {
		return keys.slice().sort((a, b) => a.t - b.t);
	}
	/** 把整段时间按缓动重映射：smooth = 整段起步缓、收尾缓，中间各段相对节奏不变。 */
	function remap(t, t0, t1, ease) {
		if (t1 - t0 < EPS || ease === "linear") return t;
		return t0 + easeInOut((t - t0) / (t1 - t0)) * (t1 - t0);
	}
	function segment(keys, t) {
		if (t <= keys[0].t) return {
			i: 0,
			u: 0
		};
		const last = keys.length - 1;
		if (t >= keys[last].t) return {
			i: Math.max(0, last - 1),
			u: last === 0 ? 0 : 1
		};
		for (let i = 0; i < last; i++) {
			const a = keys[i].t, b = keys[i + 1].t;
			if (t >= a && t <= b) return {
				i,
				u: b - a < EPS ? 1 : (t - a) / (b - a)
			};
		}
		return {
			i: last - 1,
			u: 1
		};
	}
	const filledCache = /* @__PURE__ */ new WeakMap();
	function filled(track, base) {
		let out = filledCache.get(track);
		if (out) return out;
		let pos = base.pos, rot = base.rot, scale = base.scale;
		out = sortedKeys(track.keys).map((k) => {
			pos = k.pos ?? pos;
			rot = k.rot ?? rot;
			scale = k.scale ?? scale;
			return {
				t: k.t,
				pos,
				rot,
				scale
			};
		});
		filledCache.set(track, out);
		return out;
	}
	function trackPos(keys, track, t) {
		if (keys.length === 1) return keys[0].pos;
		const { i, u } = segment(keys, remap(t, keys[0].t, keys[keys.length - 1].t, track.ease));
		if (track.path === "curve" && keys.length > 2) {
			const p0 = keys[Math.max(0, i - 1)].pos, p3 = keys[Math.min(keys.length - 1, i + 2)].pos;
			return catmull(p0, keys[i].pos, keys[i + 1].pos, p3, u);
		}
		return lerp3(keys[i].pos, keys[i + 1].pos, u);
	}
	/** 物体在 t 时刻的局部位姿（动画已作用，父级未合成）。 */
	function localPose(obj, t) {
		const base = obj.transform;
		const track = obj.track;
		if (!track || !track.keys.length) return {
			...base,
			speed: 0
		};
		const keys = filled(track, base);
		const pos = trackPos(keys, track, t);
		const { i, u } = segment(keys, remap(t, keys[0].t, keys[keys.length - 1].t, track.ease));
		const k0 = keys[i], k1 = keys[Math.min(keys.length - 1, i + 1)];
		let rot = lerp3(k0.rot, k1.rot, u);
		const scale = lerp3(k0.scale, k1.scale, u);
		const dt = 1 / 30;
		const a = trackPos(keys, track, t - dt), b = trackPos(keys, track, t + dt);
		const v = sub(b, a);
		const speed = Math.hypot(v[0], v[2]) / (2 * dt);
		if (track.face === "path") {
			let yaw = null;
			if (speed > .05) yaw = Math.atan2(v[0], v[2]) * 180 / Math.PI;
			else for (let j = Math.min(i, keys.length - 2); j >= 0 && yaw === null; j--) {
				const d = sub(keys[j + 1].pos, keys[j].pos);
				if (Math.hypot(d[0], d[2]) > EPS) yaw = Math.atan2(d[0], d[2]) * 180 / Math.PI;
			}
			if (yaw !== null) rot = [
				rot[0],
				yaw,
				rot[2]
			];
		}
		return {
			pos,
			rot,
			scale,
			speed
		};
	}
	var SceneEval = class {
		doc;
		byId = /* @__PURE__ */ new Map();
		gaitTables = /* @__PURE__ */ new Map();
		constructor(doc) {
			this.doc = doc;
			for (const o of doc.objects) this.byId.set(o.id, o);
		}
		/** 世界位姿：父级只合成平移、yaw 与缩放（足够白模预演用）。 */
		world(id, t, depth = 0) {
			const obj = this.byId.get(id);
			if (!obj) return {
				pos: [
					0,
					0,
					0
				],
				rot: [
					0,
					0,
					0
				],
				scale: [
					1,
					1,
					1
				],
				speed: 0
			};
			const local = localPose(obj, t);
			if (!obj.parent || depth > 8) return local;
			const parent = this.world(obj.parent, t, depth + 1);
			const yaw = parent.rot[1];
			const scaled = [
				local.pos[0] * parent.scale[0],
				local.pos[1] * parent.scale[1],
				local.pos[2] * parent.scale[2]
			];
			const c = Math.cos(rad(yaw)), s = Math.sin(rad(yaw));
			const rotated = [
				scaled[0] * c + scaled[2] * s,
				scaled[1],
				-scaled[0] * s + scaled[2] * c
			];
			return {
				pos: add(parent.pos, rotated),
				rot: [
					local.rot[0],
					local.rot[1] + yaw,
					local.rot[2]
				],
				scale: [
					local.scale[0] * parent.scale[0],
					local.scale[1] * parent.scale[1],
					local.scale[2] * parent.scale[2]
				],
				speed: Math.max(local.speed, parent.speed)
			};
		}
		/** 看这个物体时该对准的高度：人看眼睛，其它看中部。 */
		aimHeight(id) {
			const o = this.byId.get(id);
			if (!o) return 1;
			const h = o.size[1] * (o.transform.scale[1] || 1);
			return o.kind === "character" ? h * .9 : Math.max(.5, h * .55);
		}
		/** 人物步态相位（走过的距离 / 步幅），拖时间轴也确定。 */
		gait(id, t) {
			const o = this.byId.get(id);
			if (!o?.track) return {
				phase: 0,
				speed: 0
			};
			let table = this.gaitTables.get(id);
			if (!table) {
				const keys = o.track.keys;
				const t0 = Math.min(...keys.map((k) => k.t)), t1 = Math.max(...keys.map((k) => k.t));
				const dt = 1 / 30;
				const acc = [0];
				let prev = this.world(id, t0).pos;
				for (let x = t0 + dt; x <= t1 + dt; x += dt) {
					const p = this.world(id, x).pos;
					acc.push(acc[acc.length - 1] + Math.hypot(p[0] - prev[0], p[2] - prev[2]));
					prev = p;
				}
				table = {
					t0,
					dt,
					acc
				};
				this.gaitTables.set(id, table);
			}
			const k = clamp(Math.floor((t - table.t0) / table.dt), 0, table.acc.length - 1);
			const stride = o.track.action === "run" ? 2.4 : 1.4;
			return {
				phase: table.acc[k] / stride,
				speed: this.world(id, t).speed
			};
		}
		keyPos(key, t) {
			if (key.follow && this.byId.has(key.follow)) {
				const w = this.world(key.follow, t);
				return add(w.pos, localToWorld(key.offset ?? [
					0,
					1.6,
					-4
				], w.rot[1]));
			}
			if (key.orbit && this.byId.has(key.orbit)) return this.orbitPos(key.orbit, key.angle ?? 0, key.radius ?? 4, key.height ?? 1.6, t);
			return key.at ?? [
				0,
				1.6,
				8
			];
		}
		orbitPos(target, angle, radius, height, t) {
			const w = this.world(target, t);
			const dir = localToWorld([
				Math.sin(rad(angle)),
				0,
				Math.cos(rad(angle))
			], w.rot[1]);
			return [
				w.pos[0] + dir[0] * radius,
				w.pos[1] + height,
				w.pos[2] + dir[2] * radius
			];
		}
		keyLook(key, t, pos) {
			const look = key.look;
			if (Array.isArray(look)) return look;
			if (typeof look === "string" && this.byId.has(look)) {
				const w = this.world(look, t);
				return [
					w.pos[0],
					w.pos[1] + this.aimHeight(look),
					w.pos[2]
				];
			}
			if (look && typeof look === "object" && !Array.isArray(look) && this.byId.has(look.target)) {
				const w = this.world(look.target, t);
				return add(w.pos, localToWorld(look.offset ?? [
					0,
					this.aimHeight(look.target),
					0
				], w.rot[1]));
			}
			const target = key.follow ?? key.orbit;
			if (target && this.byId.has(target)) {
				const w = this.world(target, t);
				return [
					w.pos[0],
					w.pos[1] + this.aimHeight(target),
					w.pos[2]
				];
			}
			return add(pos, [
				0,
				-.1,
				-5
			]);
		}
		camera(cam, t) {
			const keys = sortedKeys(cam.keys);
			if (!keys.length) return {
				pos: [
					0,
					1.6,
					10
				],
				look: [
					0,
					1,
					0
				],
				lens: cam.lens,
				roll: 0
			};
			const { i, u } = segment(keys, remap(t, keys[0].t, keys[keys.length - 1].t, cam.ease));
			const k0 = keys[i], k1 = keys[Math.min(keys.length - 1, i + 1)];
			let pos;
			if (k0.orbit && k0.orbit === k1.orbit && this.byId.has(k0.orbit)) pos = this.orbitPos(k0.orbit, lerp(k0.angle ?? 0, k1.angle ?? 0, u), lerp(k0.radius ?? 4, k1.radius ?? 4, u), lerp(k0.height ?? 1.6, k1.height ?? 1.6, u), t);
			else if (cam.path === "curve" && keys.length > 2) {
				const p = (j) => this.keyPos(keys[clamp(j, 0, keys.length - 1)], t);
				pos = catmull(p(i - 1), p(i), p(i + 1), p(i + 2), u);
			} else pos = lerp3(this.keyPos(k0, t), this.keyPos(k1, t), u);
			const look = lerp3(this.keyLook(k0, t, pos), this.keyLook(k1, t, pos), u);
			const lens = lerp(k0.lens ?? cam.lens, k1.lens ?? cam.lens, u);
			const roll = lerp(k0.roll ?? 0, k1.roll ?? 0, u);
			if (cam.shake > 0) {
				const a = .05 * cam.shake;
				const n = (f, p) => Math.sin(t * f + p) + .5 * Math.sin(t * f * 2.3 + p * 1.7);
				pos = add(pos, [
					a * n(5.1, .3),
					a * .7 * n(6.3, 1.1),
					a * .5 * n(4.2, 2.2)
				]);
				return {
					pos,
					look: add(look, [
						a * .6 * n(3.7, .9),
						a * .6 * n(4.9, 1.9),
						0
					]),
					lens,
					roll: roll + cam.shake * 1.5 * n(2.9, .4)
				};
			}
			return {
				pos,
				look,
				lens,
				roll
			};
		}
		/** t 时刻主机位用的是哪台。 */
		activeCamera(t) {
			const cams = this.doc.cameras;
			if (!cams.length) return null;
			let id = this.doc.cuts.length ? this.doc.cuts[0].camera : cams[0].id;
			for (const c of this.doc.cuts) if (c.t <= t + EPS) id = c.camera;
			return cams.find((c) => c.id === id) ?? cams[0];
		}
		/** 机位在整段时间里的轨迹（画线用）。 */
		cameraTrail(cam, samples = 90) {
			const keys = sortedKeys(cam.keys);
			if (!keys.length) return [];
			const t0 = keys[0].t, t1 = Math.max(keys[keys.length - 1].t, t0 + EPS);
			const out = [];
			for (let k = 0; k <= samples; k++) out.push(this.camera({
				...cam,
				shake: 0
			}, t0 + (t1 - t0) * k / samples).pos);
			return out;
		}
		/** 关键帧此刻的实际位置（编辑时在视图里画菱形用）。 */
		keyWorld(key) {
			return this.keyPos(key, key.t);
		}
		keyLookWorld(key) {
			const p = this.keyPos(key, key.t);
			return this.keyLook(key, key.t, p);
		}
	};
	//#endregion
	//#region src/scene/runtime.ts
	var SceneError = class extends Error {};
	const MAX_OBJECTS = 5e3;
	const SKIES = [
		"day",
		"dawn",
		"dusk",
		"night",
		"overcast",
		"studio"
	];
	const GROUNDS = [
		"grid",
		"asphalt",
		"grass",
		"sand",
		"snow",
		"water",
		"stone",
		"floor",
		"dirt"
	];
	const ACTIONS = [
		"walk",
		"run",
		"drive",
		"fly",
		"swim"
	];
	function editDistance(a, b) {
		const dp = Array.from({ length: a.length + 1 }, (_, i) => [i, ...Array(b.length).fill(0)]);
		for (let j = 1; j <= b.length; j++) dp[0][j] = j;
		for (let i = 1; i <= a.length; i++) for (let j = 1; j <= b.length; j++) dp[i][j] = Math.min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
		return dp[a.length][b.length];
	}
	function suggest(name, pool, extra) {
		const scored = pool.map((p) => ({
			p,
			d: editDistance(name.toLowerCase(), p.toLowerCase())
		}));
		if (extra) {
			for (const [k, zh] of Object.entries(extra)) if (zh && (zh.includes(name) || name.includes(zh))) scored.push({
				p: k,
				d: -1
			});
		}
		scored.sort((a, b) => a.d - b.d);
		return scored.slice(0, 3).map((x) => x.p);
	}
	function makeBuilder(opts = {}) {
		const seed = Math.floor(opts.seed ?? 1);
		const random = rng(seed);
		const objects = [];
		const byId = /* @__PURE__ */ new Map();
		const cameras = [];
		const cuts = [];
		const lights = [];
		const notes = [];
		const warnings = [];
		const presetJobs = [];
		const counters = /* @__PURE__ */ new Map();
		let env = {
			sky: "day",
			ground: "grid",
			groundSize: 120,
			fog: 0
		};
		let duration = null;
		let fps = 24;
		let aspect = 16 / 9;
		const fail = (where, msg) => {
			throw new SceneError(`${where}：${msg}`);
		};
		const num = (v, where, what, dflt) => {
			if (v === void 0 || v === null) {
				if (dflt !== void 0) return dflt;
				fail(where, `缺少 ${what}`);
			}
			if (typeof v !== "number" || !Number.isFinite(v)) fail(where, `${what} 必须是数字，收到 ${JSON.stringify(v)}`);
			return v;
		};
		const vec = (v, where, what, dflt) => {
			if (v === void 0 || v === null) {
				if (dflt) return dflt;
				fail(where, `缺少 ${what}`);
			}
			if (!Array.isArray(v) || v.length !== 2 && v.length !== 3 || !v.every((x) => typeof x === "number" && Number.isFinite(x))) fail(where, `${what} 要写成 [x, z] 或 [x, y, z]（米），收到 ${JSON.stringify(v)}`);
			return v2to3(v);
		};
		const rot = (v, where, dflt = [
			0,
			0,
			0
		]) => {
			if (v === void 0 || v === null) return dflt;
			if (typeof v === "number") return [
				0,
				num(v, where, "rot"),
				0
			];
			if (Array.isArray(v) && v.length === 3) return [
				num(v[0], where, "rot[0]"),
				num(v[1], where, "rot[1]"),
				num(v[2], where, "rot[2]")
			];
			return fail(where, `rot 要写成朝向角度（数字，0 = 面向 +Z）或 [x, y, z]，收到 ${JSON.stringify(v)}`);
		};
		const scl = (v, where) => {
			if (v === void 0 || v === null) return [
				1,
				1,
				1
			];
			if (typeof v === "number") return [
				v,
				v,
				v
			];
			if (Array.isArray(v) && v.length === 3) return [
				num(v[0], where, "scale[0]"),
				num(v[1], where, "scale[1]"),
				num(v[2], where, "scale[2]")
			];
			return fail(where, `scale 要写成数字或 [x, y, z]`);
		};
		const color = (v, where) => {
			if (v === void 0 || v === null) return void 0;
			if (typeof v !== "string" || !/^#[0-9a-fA-F]{3}([0-9a-fA-F]{3})?$/.test(v)) fail(where, `color 要写成 "#rrggbb"，收到 ${JSON.stringify(v)}`);
			return v;
		};
		const get = (r, where) => {
			if (r === void 0 || r === null) return fail(where, "缺少目标（物体句柄或 id）");
			const id = typeof r === "string" ? r : r.id;
			const o = byId.get(id) ?? objects.find((x) => x.name === id);
			if (!o) {
				if (cameras.find((c) => c.id === id)) fail(where, `「${id}」是机位，这里要的是物体`);
				fail(where, `找不到物体「${id}」。已有的：${objects.slice(0, 12).map((o) => o.id).join("、")}${objects.length > 12 ? "…" : ""}`);
			}
			return o;
		};
		const cam = (r, where) => {
			const id = typeof r === "string" ? r : r?.id;
			const c = cameras.find((c) => c.id === id || c.name === id);
			if (!c) return fail(where, `找不到机位「${id}」，先用 S.camera(名字) 建一个`);
			return c;
		};
		function newId(base, explicit) {
			if (typeof explicit === "string" && explicit) {
				if (byId.has(explicit) || cameras.some((c) => c.id === explicit)) fail("id", `「${explicit}」重复了，id 要唯一`);
				return explicit;
			}
			const k = (counters.get(base) ?? 0) + 1;
			counters.set(base, k);
			let id = k === 1 ? base : `${base}#${k}`;
			while (byId.has(id)) id += "'";
			return id;
		}
		function handle(o, kind) {
			return Object.freeze({
				id: o.id,
				name: o.name,
				kind
			});
		}
		function push(o) {
			if (objects.length >= MAX_OBJECTS) fail("物体数量", `超过上限 ${MAX_OBJECTS} 个。批量摆放时减少 count，或用更大的预制件`);
			objects.push(o);
			byId.set(o.id, o);
			return handle(o, o.kind);
		}
		const known = /* @__PURE__ */ new Set([
			"at",
			"rot",
			"scale",
			"color",
			"name",
			"id",
			"parent",
			"tags"
		]);
		function place(kind, opts, where, extra) {
			const name = typeof opts.name === "string" && opts.name ? opts.name : extra.prefab ?? extra.prim ?? kind;
			const parent = opts.parent !== void 0 ? get(opts.parent, where).id : void 0;
			return push({
				id: newId(typeof opts.name === "string" && opts.name ? opts.name : name, opts.id),
				name,
				kind,
				params: {},
				parent,
				color: color(opts.color, where),
				transform: {
					pos: vec(opts.at, where, "at", [
						0,
						0,
						0
					]),
					rot: rot(opts.rot, where),
					scale: scl(opts.scale, where)
				},
				size: [
					1,
					1,
					1
				],
				tags: Array.isArray(opts.tags) ? opts.tags.map(String) : [],
				...extra
			});
		}
		const S = {
			/** 时长（秒）、画幅（"16:9"｜"9:16"｜"2.39:1"｜数字）、帧率 */
			setup(o = {}) {
				if (o.duration !== void 0) duration = clamp(num(o.duration, "S.setup", "duration"), 1, 180);
				if (o.fps !== void 0) fps = clamp(Math.round(num(o.fps, "S.setup", "fps")), 12, 60);
				if (o.aspect !== void 0) {
					if (typeof o.aspect === "number") aspect = o.aspect;
					else {
						const m = /^(\d+(?:\.\d+)?)\s*[:：x×]\s*(\d+(?:\.\d+)?)$/.exec(String(o.aspect));
						if (!m) fail("S.setup", `aspect 写成 "16:9" 这样，收到 ${JSON.stringify(o.aspect)}`);
						aspect = Number(m[1]) / Number(m[2]);
					}
				}
			},
			/** 天空、地面、雾 */
			environment(o = {}) {
				if (o.sky !== void 0 && !SKIES.includes(o.sky)) fail("S.environment", `sky 只能是 ${SKIES.join(" / ")}`);
				if (o.ground !== void 0 && !GROUNDS.includes(o.ground)) fail("S.environment", `ground 只能是 ${GROUNDS.join(" / ")}`);
				env = {
					sky: o.sky ?? env.sky,
					ground: o.ground ?? env.ground,
					groundSize: clamp(num(o.groundSize, "S.environment", "groundSize", env.groundSize), 10, 2e3),
					fog: clamp(num(o.fog, "S.environment", "fog", env.fog), 0, 1)
				};
			},
			/** 灯光：sun 太阳（dir 照射方向）、point 点光（at、range）、spot 聚光、ambient 环境光 */
			light(kind, o = {}) {
				if (![
					"sun",
					"point",
					"spot",
					"ambient"
				].includes(kind)) fail("S.light", `kind 只能是 sun / point / spot / ambient`);
				const l = {
					id: newId(o.name ?? `light-${kind}`),
					name: o.name ?? kind,
					kind,
					color: color(o.color, "S.light") ?? "#ffffff",
					intensity: num(o.intensity, "S.light", "intensity", kind === "ambient" ? .4 : 1),
					at: o.at ? vec(o.at, "S.light", "at") : void 0,
					dir: o.dir ? vec(o.dir, "S.light", "dir") : void 0,
					range: o.range !== void 0 ? num(o.range, "S.light", "range") : void 0
				};
				lights.push(l);
				return handle(l, "light");
			},
			/** 放一个预制件（见目录）。其余键是预制件参数，比如 S.add("house", {at:[0,-10], floors:2, style:"ancient"}) */
			add(prefab, o = {}) {
				const where = `S.add("${prefab}")`;
				const def = PREFABS[prefab];
				if (!def) {
					const zh = Object.fromEntries(Object.entries(PREFABS).map(([k, v]) => [k, v.zh]));
					fail(where, `没有这个预制件。最接近的：${suggest(prefab, Object.keys(PREFABS), zh).join("、")}。完整目录用 prefabs 工具看`);
				}
				const params = { ...prefabDefaults(prefab) };
				for (const [k, v] of Object.entries(o)) {
					if (known.has(k)) continue;
					if (!(k in (def.params ?? {}))) {
						warnings.push(`${where}：参数「${k}」不认识（可用：${Object.keys(def.params ?? {}).join("、") || "无"}），已忽略`);
						continue;
					}
					const spec = def.params[k];
					if (spec.options && !spec.options.includes(String(v))) fail(where, `${k} 只能是 ${spec.options.join(" / ")}，收到 ${JSON.stringify(v)}`);
					if (typeof spec.default === "number" && (typeof v !== "number" || !Number.isFinite(v))) fail(where, `${k} 要是数字，收到 ${JSON.stringify(v)}`);
					params[k] = v;
				}
				const bb = partsBounds(def.build(params));
				return place("prefab", o, where, {
					prefab,
					params,
					size: sub(bb.max, bb.min)
				});
			},
			/** 基本体：box{size:[w,h,d]}、sphere{r}、cylinder{r,h}、cone{r,h}、plane{size:[w,d]}、torus{r,tube} */
			box: (o = {}) => prim("box", o),
			sphere: (o = {}) => prim("sphere", o),
			cylinder: (o = {}) => prim("cylinder", o),
			cone: (o = {}) => prim("cone", o),
			plane: (o = {}) => prim("plane", o),
			torus: (o = {}) => prim("torus", o),
			/** 空组：把东西挂进去一起移动（其它函数的 parent 参数） */
			group(name, o = {}) {
				return place("group", {
					...o,
					name
				}, `S.group("${name}")`, { size: [
					0,
					0,
					0
				] });
			},
			/** 人物：body 体型、pose 姿势、facing 朝向（角度、点或物体） */
			character(name, o = {}) {
				const where = `S.character("${name}")`;
				const body = String(o.body ?? "male");
				if (!(body in BODIES)) fail(where, `body 只能是 ${Object.keys(BODIES).join(" / ")}`);
				const pose = String(o.pose ?? "stand");
				if (!(pose in POSES)) fail(where, `pose 只能是 ${Object.keys(POSES).join(" / ")}`);
				const at = vec(o.at, where, "at", [
					0,
					0,
					0
				]);
				let r = rot(o.rot, where);
				if (o.facing !== void 0) r = [
					0,
					facingYaw(o.facing, at, where),
					0
				];
				const h = o.height !== void 0 ? num(o.height, where, "height") : BODIES[body].height;
				return place("character", {
					...o,
					name,
					at,
					rot: r
				}, where, {
					body,
					poses: [{
						t: 0,
						pose
					}],
					ref: typeof o.ref === "string" ? o.ref : void 0,
					size: [
						.5 * BODIES[body].width,
						h,
						.3
					]
				});
			},
			/** 人物在 t 秒时换姿势（到下一次换之前一直保持） */
			pose(who, pose, t = 0) {
				const o = get(who, "S.pose");
				if (o.kind !== "character") fail("S.pose", `「${o.id}」不是人物`);
				if (!(pose in POSES)) fail("S.pose", `pose 只能是 ${Object.keys(POSES).join(" / ")}`);
				o.poses = [...(o.poses ?? []).filter((p) => Math.abs(p.t - t) > 1e-6), {
					t: num(t, "S.pose", "t"),
					pose
				}].sort((a, b) => a.t - b.t);
			},
			/** 从 from 到 to 等距摆一排 */
			row(prefab, o) {
				const where = `S.row("${prefab}")`;
				const a = vec(o.from, where, "from"), b = vec(o.to, where, "to");
				const n = Math.round(num(o.count, where, "count"));
				if (n < 1 || n > 500) fail(where, "count 要在 1–500 之间");
				const out = [];
				for (let i = 0; i < n; i++) {
					const u = n === 1 ? .5 : i / (n - 1);
					out.push(S.add(prefab, {
						...jitter(o, lerp3(a, b, u), where),
						...o.facing !== void 0 ? { rot: facingYaw(o.facing, lerp3(a, b, u), where) } : {}
					}));
				}
				return out;
			},
			/** 网格摆放：center 中心、cols×rows、spacing:[dx, dz] */
			grid(prefab, o) {
				const where = `S.grid("${prefab}")`;
				const c = vec(o.center, where, "center", [
					0,
					0,
					0
				]);
				const cols = Math.round(num(o.cols, where, "cols")), rows = Math.round(num(o.rows, where, "rows"));
				if (cols * rows > 1e3) fail(where, "cols × rows 不能超过 1000");
				const sp = typeof o.spacing === "number" ? [o.spacing, o.spacing] : o.spacing ?? [4, 4];
				const out = [];
				for (let i = 0; i < cols; i++) for (let j = 0; j < rows; j++) {
					const p = [
						c[0] + (i - (cols - 1) / 2) * sp[0],
						c[1],
						c[2] + (j - (rows - 1) / 2) * sp[1]
					];
					out.push(S.add(prefab, jitter(o, p, where)));
				}
				return out;
			},
			/** 在矩形区域 area:[x0, z0, x1, z1] 里随机撒 count 个，minGap 最小间距，avoid 避开的矩形 */
			scatter(prefab, o) {
				const where = `S.scatter("${prefab}")`;
				const area = o.area;
				if (!Array.isArray(area) || area.length !== 4) fail(where, "area 要写成 [x0, z0, x1, z1]");
				const n = Math.round(num(o.count, where, "count"));
				if (n > 800) fail(where, "count 不能超过 800");
				const gap = num(o.minGap, where, "minGap", 1.5);
				const avoid = Array.isArray(o.avoid) ? o.avoid : [];
				const pts = [];
				let tries = 0;
				while (pts.length < n && tries < n * 40) {
					tries++;
					const x = lerp(Math.min(area[0], area[2]), Math.max(area[0], area[2]), random());
					const z = lerp(Math.min(area[1], area[3]), Math.max(area[1], area[3]), random());
					if (avoid.some((r) => x >= Math.min(r[0], r[2]) && x <= Math.max(r[0], r[2]) && z >= Math.min(r[1], r[3]) && z <= Math.max(r[1], r[3]))) continue;
					if (pts.some((p) => Math.hypot(p[0] - x, p[2] - z) < gap)) continue;
					pts.push([
						x,
						0,
						z
					]);
				}
				if (pts.length < n) warnings.push(`${where}：区域太挤，只放下了 ${pts.length}/${n} 个（加大 area 或减小 minGap）`);
				return pts.map((p) => S.add(prefab, { ...jitter({
					...o,
					rotJitter: o.rotJitter ?? 180
				}, p, where) }));
			},
			/** 沿路径每隔 spacing 放一个；side：left/right/both，offset 离路中线距离；facing：path 顺路／in 朝路／out 背路 */
			along(prefab, o) {
				const where = `S.along("${prefab}")`;
				if (!Array.isArray(o.path) || o.path.length < 2) fail(where, "path 至少两个点 [[x,z], [x,z], …]");
				const pts = o.path.map((p, i) => vec(p, where, `path[${i}]`));
				const spacing = num(o.spacing, where, "spacing");
				if (spacing <= .2) fail(where, "spacing 太小");
				const side = String(o.side ?? "both");
				const off = num(o.offset, where, "offset", 0);
				const facing = String(o.facing ?? "in");
				const total = polyLength(pts);
				const out = [];
				for (let s = spacing / 2; s <= total; s += spacing) {
					const { p, dir } = samplePoly(pts, s);
					const yawPath = Math.atan2(dir[0], dir[2]) * 180 / Math.PI;
					const sides = side === "both" ? [-1, 1] : side === "left" ? [-1] : side === "right" ? [1] : [0];
					for (const sd of sides) {
						const right = rightOf(yawPath);
						const q = add(p, scale(right, sd * off));
						let yaw = yawPath;
						if (facing === "in") yaw = sd === 0 ? yawPath : yawPath + (sd > 0 ? -90 : 90);
						else if (facing === "out") yaw = sd === 0 ? yawPath : yawPath + (sd > 0 ? 90 : -90);
						out.push(S.add(prefab, jitter({
							...o,
							rot: yaw
						}, q, where)));
						if (out.length > 600) fail(where, "摆放数量超过 600，加大 spacing");
					}
				}
				return out;
			},
			/** 道路、河流：地面上的带子。kind：asphalt 柏油、stone 石板、dirt 土路、water 水面；lines 画中线 */
			road(o) {
				const where = "S.road";
				if (!Array.isArray(o.path) || o.path.length < 2) fail(where, "path 至少两个点");
				const pts = o.path.map((p, i) => vec(p, where, `path[${i}]`));
				const kind = String(o.kind ?? "asphalt");
				if (![
					"asphalt",
					"stone",
					"dirt",
					"water",
					"grass",
					"sand"
				].includes(kind)) fail(where, "kind 只能是 asphalt / stone / dirt / water / grass / sand");
				const w = num(o.width, where, "width", 8);
				const xs = pts.map((p) => p[0]), zs = pts.map((p) => p[2]);
				return place("strip", { name: o.name ?? (kind === "water" ? "河" : "路") }, where, {
					strip: {
						points: pts.map((p) => [p[0], p[2]]),
						width: w,
						kind,
						lines: o.lines ?? kind === "asphalt"
					},
					size: [
						Math.max(...xs) - Math.min(...xs) + w,
						.05,
						Math.max(...zs) - Math.min(...zs) + w
					]
				});
			},
			/** 关键帧移动：keys = [{t, at, rot?, scale?}, …]；face:"path" 朝运动方向；action：walk/run/drive/fly/swim */
			move(what, keys, o = {}) {
				const where = "S.move";
				const obj = get(what, where);
				if (!Array.isArray(keys) || !keys.length) fail(where, "keys 至少一个 {t, at}");
				obj.track = track(obj, keys.map((k, i) => ({
					t: num(k.t, where, `keys[${i}].t`),
					pos: k.at !== void 0 ? vec(k.at, where, `keys[${i}].at`) : void 0,
					rot: k.rot !== void 0 ? rot(k.rot, where) : void 0,
					scale: k.scale !== void 0 ? scl(k.scale, where) : void 0
				})), o, where);
			},
			/** 沿路径匀速走：path 点列、start 开始时间、speed（米/秒）或 duration */
			moveAlong(what, o) {
				const where = "S.moveAlong";
				const obj = get(what, where);
				if (!Array.isArray(o.path) || o.path.length < 2) fail(where, "path 至少两个点");
				let pts = o.path.map((p, i) => vec(p, where, `path[${i}]`));
				if (o.curve !== false && pts.length > 2) pts = smoothPath(pts, 6);
				const start = num(o.start, where, "start", 0);
				const total = polyLength(pts);
				const dflt = obj.kind === "character" ? o.action === "run" ? 4.5 : 1.4 : 12;
				let dur;
				if (o.duration !== void 0) dur = num(o.duration, where, "duration");
				else dur = total / num(o.speed, where, "speed", dflt);
				if (dur <= 0) fail(where, "duration 要大于 0");
				const keys = [];
				let acc = 0;
				for (let i = 0; i < pts.length; i++) {
					if (i) acc += dist(pts[i - 1], pts[i]);
					keys.push({
						t: start + (total > 0 ? acc / total * dur : 0),
						pos: pts[i]
					});
				}
				obj.transform = {
					...obj.transform,
					pos: pts[0]
				};
				obj.track = track(obj, keys, {
					face: o.face ?? "path",
					ease: o.ease ?? "linear",
					path: "linear",
					action: o.action
				}, where);
			},
			/** 建一台机位：lens 焦段（mm） */
			camera(name, o = {}) {
				const c = {
					id: newId(name || "机位", o.id),
					name: name || "机位",
					lens: clamp(num(o.lens, "S.camera", "lens", 35), 8, 300),
					keys: [],
					ease: "smooth",
					path: "curve",
					shake: clamp(num(o.shake, "S.camera", "shake", 0), 0, 1),
					presets: []
				};
				cameras.push(c);
				return handle(c, "camera");
			},
			/**
			* 机位关键帧。每个关键帧位置三选一：
			*   {t, at:[x,y,z], look}                        世界坐标
			*   {t, follow:目标, offset:[右, 上, 前]}          跟着目标走（目标自己的坐标系）
			*   {t, orbit:目标, angle, radius, height}         绕目标（angle 0 正面、90 目标右侧、180 背后）
			* look：点、物体，或 {target, offset}；跟随/环绕时默认看目标
			*/
			cameraKeys(which, keys, o = {}) {
				const where = "S.cameraKeys";
				const c = cam(which, where);
				if (!Array.isArray(keys) || !keys.length) fail(where, "keys 至少一个");
				for (const [i, k] of keys.entries()) addKey(c, normKey(k, `${where} keys[${i}]`));
				if (o.ease) c.ease = o.ease;
				if (o.path) c.path = o.path;
			},
			/** 跟拍：mode = back 背跟／front 正面跟／side 侧跟／top 顶拍／first 第一视角 */
			cameraFollow(which, target, o = {}) {
				const where = "S.cameraFollow";
				const c = cam(which, where);
				const t = get(target, where);
				const mode = String(o.mode ?? "back");
				const d = num(o.distance, where, "distance", t.kind === "character" ? 4 : 8);
				const h = num(o.height, where, "height", t.kind === "character" ? 1.8 : 2.8);
				const side = Math.sign(num(o.side, where, "side", 1)) || 1;
				const offsets = {
					back: [
						0,
						h,
						-d
					],
					front: [
						0,
						h,
						d
					],
					side: [
						side * d,
						h,
						0
					],
					top: [
						0,
						h + d * 2.5,
						-.1
					],
					first: [
						0,
						t.size[1] * .93,
						.2
					]
				};
				if (!(mode in offsets)) fail(where, `mode 只能是 ${Object.keys(offsets).join(" / ")}`);
				const s0 = num(o.start, where, "start", 0);
				const s1 = o.end !== void 0 ? num(o.end, where, "end") : null;
				const look = mode === "first" ? {
					target: t.id,
					offset: [
						0,
						t.size[1] * .9,
						12
					]
				} : void 0;
				addKey(c, {
					t: s0,
					follow: t.id,
					offset: offsets[mode],
					lens: o.lens,
					look
				});
				addKey(c, {
					t: s1 ?? s0 + .001,
					follow: t.id,
					offset: offsets[mode],
					lens: o.lens,
					look,
					...s1 === null ? { __open: true } : {}
				});
				c.ease = "linear";
			},
			/** 用预设运镜（见 camera_presets 目录）：target 目标、start/duration 时间段、side 1 右 -1 左、angle 起始角 */
			cameraPreset(which, preset, o = {}) {
				const where = `S.cameraPreset("${preset}")`;
				const c = cam(which, where);
				if (!PRESET_IDS.includes(preset)) {
					const zh = Object.fromEntries(CAMERA_PRESETS.map((p) => [p.id, p.zh]));
					fail(where, `没有这个运镜预设。最接近的：${suggest(preset, PRESET_IDS, zh).join("、")}`);
				}
				if (o.target !== void 0 && !Array.isArray(o.target)) get(o.target, where);
				presetJobs.push({
					cam: c,
					preset,
					opts: o
				});
				c.presets.push(preset);
			},
			/** 景别取景：在 t 秒给机位一个对准 target 的关键帧。size：els/ws/fs/mls/ms/mcu/cu/ecu */
			frame(which, t, target, size, o = {}) {
				const where = "S.frame";
				const c = cam(which, where);
				const obj = get(target, where);
				const lens = o.lens ?? c.lens;
				const radius = shotDistance(size, {
					size: obj.kind === "character" ? obj.size[1] : Math.max(obj.size[0], obj.size[2]),
					lens
				});
				const aim = obj.kind === "character" ? obj.size[1] * .9 : Math.max(.6, obj.size[1] * .55);
				addKey(c, {
					t: num(t, where, "t"),
					orbit: obj.id,
					angle: o.angle ?? 15,
					radius,
					height: o.height ?? aim,
					lens: o.lens
				});
			},
			/** 主机位时间表：从 t 秒起切到这台机位 */
			cut(t, which) {
				const c = cam(which, "S.cut");
				cuts.push({
					t: Math.max(0, num(t, "S.cut", "t")),
					camera: c.id
				});
			},
			/** 给导演看的说明（会出现在场景概要里） */
			note(text) {
				notes.push(String(text).slice(0, 300));
			},
			/** 按 id 或名字取回已建的物体 */
			get(id) {
				const o = get(id, "S.get");
				return handle(o, o.kind);
			},
			/** 可复现的随机：rand(a, b) 均匀、pick(数组)、chance(p) */
			rand: (a = 0, b = 1) => lerp(a, b, random()),
			pick: (arr) => arr[Math.floor(random() * arr.length)],
			chance: (p) => random() < p
		};
		function prim(kind, o) {
			const where = `S.${kind}`;
			let size;
			if (kind === "box") size = vec(o.size, where, "size", [
				1,
				1,
				1
			]);
			else if (kind === "plane") {
				const s2 = o.size ?? [4, 4];
				size = [
					num(s2[0], where, "size[0]"),
					.02,
					num(s2[1], where, "size[1]")
				];
			} else if (kind === "torus") {
				const r = num(o.r, where, "r", 1), tube = num(o.tube, where, "tube", .2);
				size = [
					r * 2,
					r * 2,
					tube * 2
				];
			} else if (kind === "sphere") {
				const r = num(o.r, where, "r", .5);
				size = [
					r * 2,
					r * 2,
					r * 2
				];
			} else {
				const r = num(o.r, where, "r", .5), h = num(o.h, where, "h", 1);
				size = [
					r * 2,
					h,
					r * 2
				];
			}
			return place("prim", o, where, {
				prim: kind,
				size,
				params: { size: size.join(",") }
			});
		}
		function jitter(o, p, where) {
			const j = num(o.jitter, where, "jitter", 0);
			const rj = num(o.rotJitter, where, "rotJitter", 0);
			const sj = num(o.scaleJitter, where, "scaleJitter", 0);
			const out = { ...o };
			for (const k of [
				"from",
				"to",
				"count",
				"center",
				"cols",
				"rows",
				"spacing",
				"area",
				"minGap",
				"avoid",
				"jitter",
				"rotJitter",
				"scaleJitter",
				"path",
				"side",
				"offset",
				"facing",
				"name",
				"id"
			]) delete out[k];
			out.at = [
				p[0] + (j ? (random() - .5) * 2 * j : 0),
				p[1],
				p[2] + (j ? (random() - .5) * 2 * j : 0)
			];
			const baseYaw = typeof o.rot === "number" ? o.rot : Array.isArray(o.rot) ? o.rot[1] : 0;
			if (rj) out.rot = baseYaw + (random() - .5) * 2 * rj;
			if (sj) out.scale = 1 + (random() - .5) * 2 * sj;
			return out;
		}
		function facingYaw(f, from, where) {
			if (typeof f === "number") return f;
			if (Array.isArray(f)) return yawTo(from, vec(f, where, "facing"));
			const o = get(f, where);
			return yawTo(from, o.transform.pos);
		}
		function track(obj, keys, o, where) {
			const action = o.action;
			if (action !== void 0 && !ACTIONS.includes(action)) fail(where, `action 只能是 ${ACTIONS.join(" / ")}`);
			const sorted = keys.slice().sort((a, b) => a.t - b.t);
			if (sorted.length > 800) fail(where, "关键帧太多（>800）");
			if (!sorted[0].pos) sorted[0] = {
				...sorted[0],
				pos: obj.transform.pos
			};
			const steered = obj.kind === "character" || [
				"car",
				"police_car",
				"truck",
				"bus",
				"motorcycle",
				"bicycle",
				"boat",
				"horse",
				"horse_cart",
				"helicopter",
				"bird",
				"dog",
				"cart"
			].includes(obj.prefab ?? "");
			const face = o.face ?? (steered ? "path" : "none");
			return {
				keys: sorted,
				ease: o.ease === "linear" ? "linear" : o.ease === "smooth" ? "smooth" : "smooth",
				path: o.path === "curve" ? "curve" : "linear",
				face: face === "path" ? "path" : "none",
				action: action ?? (obj.kind === "character" ? "walk" : void 0)
			};
		}
		function normKey(k, where) {
			const out = { t: num(k.t, where, "t") };
			if ((k.at !== void 0 ? 1 : 0) + (k.follow !== void 0 ? 1 : 0) + (k.orbit !== void 0 ? 1 : 0) !== 1) fail(where, "位置要在 at / follow / orbit 里三选一");
			if (k.at !== void 0) out.at = vec(k.at, where, "at");
			if (k.follow !== void 0) {
				out.follow = get(k.follow, where).id;
				out.offset = vec(k.offset, where, "offset", [
					0,
					1.7,
					-4
				]);
			}
			if (k.orbit !== void 0) {
				out.orbit = get(k.orbit, where).id;
				out.angle = num(k.angle, where, "angle", 0);
				out.radius = num(k.radius, where, "radius", 4);
				out.height = num(k.height, where, "height", 1.6);
			}
			if (k.look !== void 0) {
				const l = k.look;
				if (Array.isArray(l)) out.look = vec(l, where, "look");
				else if (typeof l === "string" || l && typeof l === "object" && "id" in l) out.look = get(l, where).id;
				else if (l && typeof l === "object" && "target" in l) {
					const lo = l;
					out.look = {
						target: get(lo.target, where).id,
						offset: lo.offset ? vec(lo.offset, where, "look.offset") : void 0
					};
				} else fail(where, "look 要写成点 [x,y,z]、物体，或 {target, offset}");
			}
			if (k.lens !== void 0) out.lens = clamp(num(k.lens, where, "lens"), 8, 300);
			if (k.roll !== void 0) out.roll = num(k.roll, where, "roll");
			return out;
		}
		function addKey(c, k) {
			c.keys = [...c.keys.filter((x) => Math.abs(x.t - k.t) > 1e-6), k].sort((a, b) => a.t - b.t);
		}
		function finish(error) {
			const keyTimes = [
				...objects.flatMap((o) => o.track?.keys.map((k) => k.t) ?? []),
				...cameras.flatMap((c) => c.keys.map((k) => k.t)),
				...cuts.map((c) => c.t),
				...presetJobs.map((j) => (typeof j.opts.start === "number" ? j.opts.start : 0) + (typeof j.opts.duration === "number" ? j.opts.duration : 4))
			].filter((t) => Number.isFinite(t));
			const dur = duration ?? clamp(Math.max(5, ...keyTimes.map((t) => Math.ceil(t))), 1, 180);
			const draft = {
				version: 1,
				duration: dur,
				fps,
				aspect,
				seed,
				env,
				lights: lights.slice(),
				objects,
				cameras,
				cuts: [],
				notes
			};
			const ev = new SceneEval(draft);
			for (const job of presetJobs) {
				const o = job.opts;
				const where = `S.cameraPreset("${job.preset}")`;
				try {
					const def = CAMERA_PRESETS.find((p) => p.id === job.preset);
					let target = null;
					let point = [
						0,
						0,
						0
					];
					if (Array.isArray(o.target)) point = vec(o.target, where, "target");
					else if (o.target !== void 0) target = get(o.target, where).id;
					const obj = target ? byId.get(target) : null;
					const size = obj ? obj.kind === "character" ? obj.size[1] : Math.max(obj.size[0], obj.size[2], obj.size[1]) : 1.75;
					const aim = obj ? obj.kind === "character" ? obj.size[1] * .9 : Math.max(.6, obj.size[1] * .55) : 1.2;
					const res = def.build({
						target,
						start: num(o.start, where, "start", 0),
						duration: Math.max(.2, num(o.duration, where, "duration", 4)),
						side: num(o.side, where, "side", 1) < 0 ? -1 : 1,
						lens: num(o.lens, where, "lens", job.cam.lens),
						size,
						aim,
						angle: num(o.angle, where, "angle", 15),
						distance: o.distance !== void 0 ? num(o.distance, where, "distance") : void 0,
						height: o.height !== void 0 ? num(o.height, where, "height") : void 0,
						posAt: (t) => target ? ev.world(target, t).pos : point,
						yawAt: (t) => target ? ev.world(target, t).rot[1] : 0
					});
					for (const k of res.keys) addKey(job.cam, k);
					if (res.shake !== void 0) job.cam.shake = Math.max(job.cam.shake, res.shake);
					if (res.ease) job.cam.ease = res.ease;
					if (res.path) job.cam.path = res.path;
				} catch (e) {
					warnings.push(e instanceof Error ? e.message : String(e));
				}
			}
			for (const c of cameras) c.keys = c.keys.map((k) => k.__open ? {
				...k,
				t: dur,
				__open: void 0
			} : k).map((k) => {
				const { __open, ...rest } = k;
				return rest;
			}).sort((a, b) => a.t - b.t);
			if (!cameras.length && objects.length) {
				const c = S.camera("默认机位");
				const bb = boundsOf(objects);
				const cx = (bb.min[0] + bb.max[0]) / 2, cz = (bb.min[1] + bb.max[1]) / 2;
				const span = Math.max(10, bb.max[0] - bb.min[0], bb.max[1] - bb.min[1]);
				addKey(cameras[0], {
					t: 0,
					at: [
						cx,
						span * .35,
						bb.max[1] + span * .6
					],
					look: [
						cx,
						1,
						cz
					]
				});
				warnings.push(`没有机位：自动放了「${c.name}」俯瞰全场。要出成片请用 S.camera + S.cameraKeys / S.cameraPreset 设计机位`);
			}
			for (const c of cameras) if (!c.keys.length) warnings.push(`机位「${c.name}」没有关键帧（S.cameraKeys / S.cameraPreset / S.frame），成片里会停在默认位置`);
			let finalCuts = cuts.slice().sort((a, b) => a.t - b.t);
			if (!finalCuts.length && cameras.length) finalCuts = [{
				t: 0,
				camera: cameras[0].id
			}];
			if (finalCuts.length && finalCuts[0].t > 0) finalCuts.unshift({
				t: 0,
				camera: finalCuts[0].camera
			});
			for (const ct of finalCuts) if (ct.t > dur) warnings.push(`S.cut(${ct.t})：超出片长 ${dur}s`);
			applyOverrides(draft, opts.overrides, warnings);
			const doc = {
				...draft,
				cuts: opts.overrides?.cuts?.length ? opts.overrides.cuts : finalCuts
			};
			for (const o of objects) {
				const p = o.transform.pos;
				if (!o.parent && o.kind !== "strip" && Math.max(Math.abs(p[0]), Math.abs(p[2])) > env.groundSize / 2 + 5 && !(o.prefab === "mountain")) warnings.push(`「${o.id}」在地面外（${p[0].toFixed(0)}, ${p[2].toFixed(0)}），地面边长 ${env.groundSize}m；要么挪近，要么加大 S.environment({groundSize})`);
				if (o.track) {
					for (const k of o.track.keys) if (k.t > dur + 1e-6) {
						warnings.push(`「${o.id}」的动画关键帧 t=${k.t} 超出片长 ${dur}s`);
						break;
					}
				}
			}
			const dup = /* @__PURE__ */ new Map();
			for (const o of objects) if (o.kind !== "group" && o.kind !== "strip") {
				const key = `${o.prefab ?? o.prim}@${o.transform.pos.map((v) => v.toFixed(1)).join(",")}`;
				dup.set(key, (dup.get(key) ?? 0) + 1);
			}
			const dups = [...dup.entries()].filter(([, k]) => k > 1);
			if (dups.length) warnings.push(`有 ${dups.length} 处同一位置重复摆了同样的东西（比如 ${dups[0][0]}）`);
			const summary = objects.length || cameras.length ? summarize(doc, ev) : null;
			return {
				doc,
				diagnostics: {
					ok: !error,
					errors: error ? [error] : [],
					warnings: [...new Set(warnings)].slice(0, 40),
					summary
				}
			};
		}
		return {
			S,
			/** 给脚本用的向量小工具 */
			V: {
				add,
				sub,
				scale,
				len,
				dist,
				lerp: lerp3,
				norm,
				/** 朝向 yaw（度）的前方向量 */ forward: forwardOf,
				/** 从 a 看向 b 的朝向角 */ yawTo,
				/** 以 center 为圆心、半径 r、角度 deg 处的点（0° = +Z） */
				polar: (center, r, deg) => {
					const c = v2to3(center);
					return [
						c[0] + Math.sin(rad(deg)) * r,
						c[1],
						c[2] + Math.cos(rad(deg)) * r
					];
				},
				/** 圆上等分 n 个点 */
				circle: (center, r, n) => Array.from({ length: n }, (_, i) => {
					const c = v2to3(center);
					const a = i / n * Math.PI * 2;
					return [
						c[0] + Math.sin(a) * r,
						c[1],
						c[2] + Math.cos(a) * r
					];
				})
			},
			random,
			finish
		};
	}
	function applyOverrides(doc, ov, warnings = []) {
		if (!ov) return doc;
		const byId = new Map(doc.objects.map((o) => [o.id, o]));
		for (const [id, o] of Object.entries(ov.objects ?? {})) {
			const obj = byId.get(id);
			if (!obj) {
				warnings.push(`手动改动里的「${id}」在脚本里已经不存在（脚本改名或删掉了），这条改动没生效`);
				continue;
			}
			obj.transform = {
				pos: o.pos ?? obj.transform.pos,
				rot: o.rot ?? obj.transform.rot,
				scale: o.scale ?? obj.transform.scale
			};
			if (o.color) obj.color = o.color;
			if (o.hidden) obj.tags = [...obj.tags.filter((t) => t !== "hidden"), "hidden"];
			if (obj.track && o.pos) {
				const first = obj.track.keys[0];
				if (first?.pos) {
					const d = sub(o.pos, first.pos);
					obj.track = {
						...obj.track,
						keys: obj.track.keys.map((k) => k.pos ? {
							...k,
							pos: add(k.pos, d)
						} : k)
					};
				}
			}
		}
		for (const [id, c] of Object.entries(ov.cameras ?? {})) {
			const cam = doc.cameras.find((x) => x.id === id);
			if (!cam) {
				warnings.push(`手动改动里的机位「${id}」在脚本里已经不存在`);
				continue;
			}
			if (c.keys) cam.keys = c.keys.slice().sort((a, b) => a.t - b.t);
			if (c.lens) cam.lens = c.lens;
			if (c.ease) cam.ease = c.ease;
			if (c.path) cam.path = c.path;
		}
		return doc;
	}
	function boundsOf(objects) {
		const xs = [], zs = [];
		for (const o of objects) {
			if (o.prefab === "mountain") continue;
			if (o.strip) for (const p of o.strip.points) {
				xs.push(p[0]);
				zs.push(p[1]);
			}
			else {
				xs.push(o.transform.pos[0]);
				zs.push(o.transform.pos[2]);
			}
		}
		if (!xs.length) return {
			min: [0, 0],
			max: [0, 0]
		};
		return {
			min: [Math.min(...xs), Math.min(...zs)],
			max: [Math.max(...xs), Math.max(...zs)]
		};
	}
	/** 概要＋俯视字符地图：智能体靠它检查布局，不用截图。 */
	function summarize(doc, ev) {
		const counts = {};
		for (const o of doc.objects) {
			const k = o.kind === "prefab" ? `${o.prefab}（${PREFABS[o.prefab]?.zh ?? ""}）` : o.kind === "character" ? "人物" : o.kind === "strip" ? `${o.strip?.kind === "water" ? "河" : "路"}` : o.kind === "prim" ? `基本体 ${o.prim}` : "组";
			counts[k] = (counts[k] ?? 0) + 1;
		}
		const bb = boundsOf(doc.objects);
		const moving = (o) => !!o.track?.keys.length;
		const pos = (o, t) => ev.world(o.id, t).pos.map((v) => +v.toFixed(1));
		const lastT = (o) => Math.max(...o.track?.keys.map((k) => k.t) ?? [0]);
		const characters = doc.objects.filter((o) => o.kind === "character").map((o) => ({
			id: o.id,
			name: o.name,
			body: o.body ?? "male",
			from: pos(o, 0),
			to: pos(o, moving(o) ? lastT(o) : 0),
			action: o.track?.action
		}));
		const VEHICLES = /* @__PURE__ */ new Set([
			"car",
			"police_car",
			"truck",
			"bus",
			"motorcycle",
			"bicycle",
			"boat",
			"helicopter",
			"horse_cart",
			"horse"
		]);
		const vehicles = doc.objects.filter((o) => o.prefab && VEHICLES.has(o.prefab)).map((o) => ({
			id: o.id,
			name: o.name,
			from: pos(o, 0),
			to: pos(o, moving(o) ? lastT(o) : 0)
		}));
		const cameras = doc.cameras.map((c) => ({
			id: c.id,
			name: c.name,
			keys: c.keys.length,
			span: [c.keys[0]?.t ?? 0, c.keys[c.keys.length - 1]?.t ?? 0],
			kinds: [...new Set(c.keys.map((k) => k.follow ? "跟随" : k.orbit ? "环绕" : "世界坐标"))],
			presets: c.presets
		}));
		return {
			duration: doc.duration,
			objects: doc.objects.length,
			counts,
			bounds: {
				min: bb.min.map((v) => +v.toFixed(1)),
				max: bb.max.map((v) => +v.toFixed(1))
			},
			characters,
			vehicles,
			cameras,
			cuts: doc.cuts,
			map: asciiMap(doc, ev),
			notes: doc.notes
		};
	}
	function asciiMap(doc, ev, W = 56, Hh = 26) {
		const bb = boundsOf(doc.objects);
		const pad = 4;
		const x0 = bb.min[0] - pad, x1 = bb.max[0] + pad, z0 = bb.min[1] - pad, z1 = bb.max[1] + pad;
		const sx = (x1 - x0) / W || 1, sz = (z1 - z0) / Hh || 1;
		const cell = Math.max(sx, sz);
		const cols = Math.min(W, Math.ceil((x1 - x0) / cell) + 1), rows = Math.min(Hh, Math.ceil((z1 - z0) / cell) + 1);
		const grid = Array.from({ length: rows }, () => Array(cols).fill("·"));
		const put = (x, z, ch, force = false) => {
			const c = Math.round((x - x0) / cell), r = Math.round((z - z0) / cell);
			if (r >= 0 && r < rows && c >= 0 && c < cols && (force || grid[r][c] === "·" || grid[r][c] === "=" || grid[r][c] === "~")) grid[r][c] = ch;
		};
		for (const o of doc.objects) if (o.strip) {
			const pts = o.strip.points.map((p) => [
				p[0],
				0,
				p[1]
			]);
			const total = polyLength(pts);
			for (let s = 0; s <= total; s += cell * .7) {
				const { p } = samplePoly(pts, s);
				put(p[0], p[2], o.strip.kind === "water" ? "~" : "=");
			}
		}
		const GLYPH = {
			house: "#",
			building: "#",
			skyscraper: "#",
			shop: "#",
			pagoda: "#",
			pavilion: "#",
			gate: "#",
			well: "#",
			stall: "#",
			tree: "T",
			bush: "T",
			car: "C",
			police_car: "C",
			truck: "C",
			bus: "C",
			motorcycle: "C",
			bicycle: "C",
			helicopter: "C",
			horse_cart: "C",
			cart: "C",
			boat: "B",
			wall: "|",
			fence: "|",
			bridge: "H",
			mountain: "",
			marker: "",
			arrow: ""
		};
		const glyph = (o) => {
			if (o.kind === "character") return "@";
			if (o.kind === "group") return "";
			return GLYPH[o.prefab ?? ""] ?? "o";
		};
		for (const o of doc.objects) {
			const g = glyph(o);
			if (!g || o.strip) continue;
			const w = ev.world(o.id, 0).pos;
			put(w[0], w[2], g, g === "@" || g === "C");
		}
		doc.cameras.forEach((c, i) => {
			if (!c.keys.length) return;
			const p = ev.camera(c, c.keys[0].t).pos;
			put(p[0], p[2], String((i + 1) % 10), true);
		});
		const lines = grid.map((r) => r.join(""));
		return [
			`俯视图（北 = -Z 在上；每格约 ${cell.toFixed(1)}m；x ${x0.toFixed(0)}→${x1.toFixed(0)}，z ${z0.toFixed(0)}→${z1.toFixed(0)}）`,
			"图例：# 建筑  T 树  C 车  B 船  @ 人物  | 墙栏  H 桥  = 路  ~ 水  o 其它  数字 = 机位起点",
			...lines
		].join("\n");
	}
	//#endregion
	//#region src/scene/shot.ts
	const IMPORTANT = /* @__PURE__ */ new Set([
		"car",
		"police_car",
		"truck",
		"bus",
		"motorcycle",
		"bicycle",
		"boat",
		"helicopter",
		"horse",
		"horse_cart",
		"bird",
		"dog"
	]);
	function describePos(x, y) {
		const h = x < -.33 ? "左" : x > .33 ? "右" : "中";
		const v = y > .33 ? "上" : y < -.33 ? "下" : "中";
		return h === "中" && v === "中" ? "画面正中" : `画面${v === "中" ? "" : v}${h === "中" ? "中" : h}${v === "中" ? "侧" : ""}`;
	}
	function sizeWord(frac) {
		if (frac > 1.2) return "大特写（画不下）";
		if (frac > .75) return "特写";
		if (frac > .45) return "近景";
		if (frac > .25) return "中景";
		if (frac > .1) return "全景";
		if (frac > .03) return "远景";
		return "极小";
	}
	/** 包围球（半径、中心）：挡没挡住用它判断就够了 */
	function sphere(ev, o, t) {
		const w = ev.world(o.id, t);
		const s = o.size;
		const k = Math.max(w.scale[0], w.scale[1], w.scale[2]);
		return {
			c: [
				w.pos[0],
				w.pos[1] + s[1] * w.scale[1] / 2,
				w.pos[2]
			],
			r: Math.max(s[0], s[2], s[1] * .6) * k / 2
		};
	}
	function shotReport(doc, camId, t) {
		const ev = new SceneEval(doc);
		const cam = doc.cameras.find((c) => c.id === camId || c.name === camId);
		if (!cam) return `没有机位「${camId}」`;
		const p = ev.camera({
			...cam,
			shake: 0
		}, t);
		const fwd = norm(sub(p.look, p.pos));
		const right = norm([
			-fwd[2],
			0,
			fwd[0]
		]);
		const up = [
			right[1] * fwd[2] - right[2] * fwd[1],
			right[2] * fwd[0] - right[0] * fwd[2],
			right[0] * fwd[1] - right[1] * fwd[0]
		];
		const tanH = 18 / p.lens, tanV = tanH / doc.aspect;
		const pitch = deg(Math.asin(clamp(fwd[1], -1, 1)));
		const lines = [`机位「${cam.name}」在 ${t.toFixed(1)}s：位置 [${p.pos.map((v) => v.toFixed(1)).join(", ")}]，看向 [${p.look.map((v) => v.toFixed(1)).join(", ")}]，${Math.round(p.lens)}mm，${pitch < -35 ? "大俯拍" : pitch < -10 ? "俯拍" : pitch > 20 ? "大仰拍" : pitch > 6 ? "仰拍" : "平视"}（俯仰 ${pitch.toFixed(0)}°）`];
		const cands = doc.objects.filter((o) => !o.tags.includes("hidden") && o.kind !== "strip" && o.kind !== "group" && o.prefab !== "mountain" && o.prefab !== "marker");
		const spheres = new Map(cands.map((o) => [o.id, sphere(ev, o, t)]));
		const seen = [];
		for (const o of cands) {
			const s = spheres.get(o.id);
			const rel = sub(s.c, p.pos);
			const z = dot(rel, fwd);
			if (z < .3) continue;
			const x = dot(rel, right) / (z * tanH), y = dot(rel, up) / (z * tanV);
			const hFrac = o.size[1] * ev.world(o.id, t).scale[1] / (2 * z * tanV);
			if (Math.abs(x) - s.r / (z * tanH) > 1 || Math.abs(y) - s.r / (z * tanV) > 1) continue;
			seen.push({
				o,
				x,
				y,
				frac: hFrac,
				dist: z,
				occ: []
			});
		}
		const named = (o) => o.kind === "character" || IMPORTANT.has(o.prefab ?? "") || !/#\d+$/.test(o.id) && o.name !== o.prefab;
		const important = seen.filter((v) => named(v.o));
		for (const v of important) {
			const target = spheres.get(v.o.id);
			const seg = sub(target.c, p.pos);
			const L = len(seg);
			const d = scale(seg, 1 / L);
			for (const other of seen) {
				if (other.o.id === v.o.id || other.dist >= v.dist) continue;
				const s = spheres.get(other.o.id);
				const along = dot(sub(s.c, p.pos), d);
				if (along <= 0 || along >= L - target.r) continue;
				const closest = add(p.pos, scale(d, along));
				if (dist(closest, s.c) < s.r * .85) v.occ.push(other.o.name);
			}
		}
		const rows = seen.filter((v) => named(v.o)).sort((a, b) => b.frac - a.frac).slice(0, 12);
		if (!rows.length) lines.push("画面里没有人物、载具或起了名字的物体（可能对着空地、天空或墙）");
		for (const v of rows) {
			const kind = v.o.kind === "character" ? "人物" : PREFABS[v.o.prefab ?? ""]?.zh ?? v.o.kind;
			lines.push(`- ${v.o.name}（${kind}）：${describePos(v.x, v.y)}（x ${Math.round((v.x + 1) * 50)}%，y ${Math.round((1 - v.y) * 50)}%），高度占画面 ${Math.round(v.frac * 100)}%（${sizeWord(v.frac)}），距离 ${v.dist.toFixed(1)}m` + (v.occ.length ? `；被挡住：${[...new Set(v.occ)].slice(0, 3).join("、")}` : ""));
		}
		const bg = seen.filter((v) => !named(v.o));
		if (bg.length) {
			const counts = {};
			for (const v of bg) {
				const k = PREFABS[v.o.prefab ?? ""]?.zh ?? v.o.kind;
				counts[k] = (counts[k] ?? 0) + 1;
			}
			lines.push(`背景里还有：${Object.entries(counts).map(([k, n]) => `${k}×${n}`).join("、")}`);
		}
		return lines.join("\n");
	}
	//#endregion
	//#region src/scene/iife.ts
	/**
	* 场景运行时的沙箱入口：打成 IIFE 放进 ainer-core/app/scene3d/vendor/，
	* 由 runner.mjs 在 vm 上下文**里面**执行 —— 构建器活在沙箱自己的 realm 里，
	* 脚本摸不到任何宿主对象。
	*/
	globalThis.SceneRuntime = {
		makeBuilder,
		applyOverrides,
		shotReport,
		catalog: () => ({
			...catalogDoc(),
			cameraPresets: presetDoc()
		})
	};
	//#endregion
})();
